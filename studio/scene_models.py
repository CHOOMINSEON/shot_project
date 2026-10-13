"""Local CPU models. Pinned revisions and checksums; never upload user frames."""
import hashlib
import threading
from pathlib import Path

import httpx
import numpy as np
from filelock import FileLock
from .settings import DATA

DIRECTORY = DATA / 'models' / 'scene-search-v1'
CLIP_REV = 'd15189d7028b43f1d3e65039190477f6af591c2a'
OCR_REV = '7b02d0a30a07ba2b92ad1ff5a8941ae2c633de65'
FILES = [
 ('vision.onnx','Xenova/clip-vit-base-patch32',CLIP_REV,'onnx/vision_model_quantized.onnx','sha256','583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299',89117001),
 ('text.onnx','Xenova/clip-vit-base-patch32',CLIP_REV,'onnx/text_model_quantized.onnx','sha256','73baab855d406190da9faa498cfedf65f15cf309f4cc7385b7b032e6d08e5c3a',64504507),
 ('tokenizer.json','Xenova/clip-vit-base-patch32',CLIP_REV,'tokenizer.json','gitsha1','bc1f77d20440541dd073ebae6f6c401087c7d34e',2224119),
 ('det.onnx','monkt/paddleocr-onnx',OCR_REV,'detection/v3/det.onnx','sha256','ee40e80071ba3a320d4efda75f3e22047a7d049e9bf7bcaaf9daea23fc21b935',2429873),
 ('rec.onnx','monkt/paddleocr-onnx',OCR_REV,'languages/korean/rec.onnx','sha256','322f140154c820fcb83c3d24cfe42c9ec70dd1a1834163306a7338136e4f1eaa',13401252),
 ('dict.txt','monkt/paddleocr-onnx',OCR_REV,'languages/korean/dict.txt','gitsha1','e2202631098b4e49662ed4d29a380df4cbf6de78',47451),
]
MODEL = None
LOCK = threading.Lock()


def digest(path, algorithm):
    h = hashlib.sha1() if algorithm=='gitsha1' else hashlib.sha256()
    if algorithm=='gitsha1':h.update(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as source:
        while chunk:=source.read(1024*1024):h.update(chunk)
    return h.hexdigest()


def ensure(check=lambda:None, progress=lambda message:None):
    DIRECTORY.mkdir(parents=True,exist_ok=True)
    with FileLock(DIRECTORY/'download.lock',timeout=600):
        with httpx.Client(follow_redirects=True,timeout=httpx.Timeout(120,connect=30)) as client:
            for name,repo,rev,remote,algorithm,expected,size in FILES:
                check();path=DIRECTORY/name
                if path.exists() and path.stat().st_size==size and digest(path,algorithm)==expected:continue
                progress(f'장면·한국어 OCR 모델 준비: {name} · 처음 한 번 약 172MB')
                tmp=path.with_suffix(path.suffix+'.partial')
                with client.stream('GET',f'https://huggingface.co/{repo}/resolve/{rev}/{remote}') as response:
                    response.raise_for_status()
                    with tmp.open('wb') as target:
                        received=0
                        for chunk in response.iter_bytes(1024*1024):
                            check();received+=len(chunk)
                            if received>size:raise ValueError('장면 모델 크기 검증 실패')
                            target.write(chunk)
                if tmp.stat().st_size!=size or digest(tmp,algorithm)!=expected:
                    raise ValueError('장면 모델 체크섬 검증 실패 · 재시도해 주세요.')
                tmp.replace(path)


def unit(value):
    value=np.asarray(value,dtype=np.float32)
    return value/np.maximum(np.linalg.norm(value,axis=-1,keepdims=True),1e-8)


class Vision:
    def __init__(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        from rapidocr_onnxruntime import RapidOCR
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        self.image_session=ort.InferenceSession(str(DIRECTORY/'vision.onnx'),options,providers=['CPUExecutionProvider'])
        self.text_session=ort.InferenceSession(str(DIRECTORY/'text.onnx'),options,providers=['CPUExecutionProvider'])
        self.tokenizer=Tokenizer.from_file(str(DIRECTORY/'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=77)
        self.tokenizer.enable_padding(length=77,pad_id=49407,pad_token='<|endoftext|>')
        self.ocr=RapidOCR(det_model_path=str(DIRECTORY/'det.onnx'),rec_model_path=str(DIRECTORY/'rec.onnx'),
                          rec_keys_path=str(DIRECTORY/'dict.txt'),rec_img_shape=[3,48,320],
                          intra_op_num_threads=2,inter_op_num_threads=1,use_cls=False)
        self.cache={}

    def texts(self,texts):
        absent=list(dict.fromkeys(t for t in texts if t not in self.cache))
        for start in range(0,len(absent),16):
            batch=absent[start:start+16];enc=self.tokenizer.encode_batch(batch)
            ids=np.asarray([e.ids for e in enc],dtype=np.int64)
            masks=np.asarray([e.attention_mask for e in enc],dtype=np.int64)
            supplied={'input_ids':ids,'attention_mask':masks}
            inputs={i.name:supplied[i.name] for i in self.text_session.get_inputs()}
            embedding=unit(self.text_session.run(None,inputs)[0])
            for name,vector in zip(batch,embedding):self.cache[name]=vector
        return np.asarray([self.cache[t] for t in texts])

    def image(self,image):
        from PIL import Image
        image=image.convert('RGB');w,h=image.size;scale=224/min(w,h)
        image=image.resize((round(w*scale),round(h*scale)),Image.Resampling.BICUBIC)
        w,h=image.size;image=image.crop(((w-224)//2,(h-224)//2,(w+224)//2,(h+224)//2))
        data=np.asarray(image,dtype=np.float32)/255
        data=(data-np.array([.48145466,.4578275,.40821073]))/np.array([.26862954,.26130258,.27577711])
        data=data.transpose(2,0,1)[None].astype(np.float32)
        return unit(self.image_session.run(None,{self.image_session.get_inputs()[0].name:data})[0])[0]

    def read(self,image):
        # Keep full-frame OCR: center-cropping would miss package labels near edges.
        result,_=self.ocr(np.asarray(image.convert('RGB'))[:,:,::-1],use_cls=False)
        return [{'text':r[1],'confidence':round(float(r[2]),4),'box':np.asarray(r[0]).round(1).tolist()}
                for r in result or [] if r[2]>=.65]


def load(check=lambda:None,progress=lambda message:None):
    global MODEL
    with LOCK:
        if MODEL is None:
            ensure(check,progress);check();MODEL=Vision()
    return MODEL


def views(image):
    """The same observation crops for video and user-provided reference images."""
    from PIL import Image
    square=Image.new('RGB',(max(image.size),max(image.size)),(127,127,127))
    square.paste(image,((square.width-image.width)//2,(square.height-image.height)//2))
    return [(image,[0,0,1,1]),(image.crop((0,image.height//2,image.width,image.height)),[0,.5,1,1]),(square,[0,0,1,1])]
