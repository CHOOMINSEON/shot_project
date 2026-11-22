/* 4. 캡션 자막 탭: 생성, SRT 다운로드, 자막 목록(시간 + 문구). 문구를 고치면 미리보기 자막이 바로 바뀌고 잠시 뒤 저장된다. */
(function(){
const list=$('cap-list');if(!list)return;
let saveTimer=null,pending=null;
const items=()=>project?.state.captions?.items||[];
const autosize=t=>{t.style.height='auto';t.style.height=t.scrollHeight+'px';};
function render(){
  if(!project)return;const a=document.activeElement;if(a&&list.contains(a)&&a.tagName==='TEXTAREA')return; // 쓰는 중에는 다시 그리지 않음
  const caps=items();
  list.innerHTML=(caps.length&&!captionSynced()?'<p class="cap-warn">컷이 바뀌었어요. 생성을 다시 눌러 주세요.</p>':'')+
    caps.map((c,i)=>`<div class="cap-row" data-row="${i}"><button type="button" class="cap-time" data-cap-seek="${i}">${clock(c.start)}</button><textarea data-cap="${i}" rows="1" spellcheck="false">${esc(c.text)}</textarea></div>`).join('');
  list.querySelectorAll('textarea').forEach(autosize);mark();
}
const orig=window.drawCaptions;
window.drawCaptions=function(){orig?.apply(this,arguments);render();};
// 재생 위치의 자막 줄 표시
function mark(){if(!project||mode!=='edited')return;const t=editedPosition();
  list.querySelectorAll('.cap-row').forEach(r=>{const c=items()[+r.dataset.row];r.classList.toggle('now',!!c&&c.start<=t&&c.end>t);});}
$('player').addEventListener('timeupdate',()=>{mark();if(pending)overlay(pending.i,pending.text);});
$('player').addEventListener('seeked',()=>{if(pending)overlay(pending.i,pending.text);});
function overlay(i,text){const c=items()[i];if(!c||mode!=='edited'||!$('show-captions')?.checked)return;const t=editedPosition();if(c.start<=t&&c.end>t)$('caption-overlay').textContent=text;}
function save(){if(!pending)return Promise.resolve();const {i,text}=pending;clearTimeout(saveTimer);
  return mutate(s=>{const c=s.captions.items[i];if(c&&c.text!==text)Object.assign(c,{text,edited:true,review:true,review_token:''});}).then(()=>{if(pending&&pending.i===i&&pending.text===text)pending=null;}).catch(e=>{pending=null;toast(e.message);});}
list.addEventListener('input',e=>{const t=e.target.closest('[data-cap]');if(!t)return;autosize(t);const i=+t.dataset.cap;
  overlay(i,t.value);pending={i,text:t.value};clearTimeout(saveTimer);saveTimer=setTimeout(save,500);});
list.addEventListener('focusout',e=>{if(e.target.closest('[data-cap]'))save().then(()=>setTimeout(render,0));});
// 줄을 누르면 그 자막 시간으로 이동(멈춤)
list.addEventListener('click',e=>{const r=e.target.closest('.cap-row');const i=r?+r.dataset.row:null;
  if(i===null||!items()[i])return;$('player').pause();seekEdited(items()[i].start+.01,false);setTimeout(()=>window.timelineKeepVisible?.(),150);});
action('cap-generate',async()=>{await save();$('generate-captions').click();});
action('cap-srt',async()=>{requireProject();await save();await saveQueue;
  if(!items().length)throw Error('먼저 생성을 눌러 자막을 만들어 주세요.');
  if(!captionSynced())throw Error('컷이 바뀌었어요. 생성을 다시 눌러 주세요.');
  const todo=items().filter(c=>c.text.trim()&&!c.reviewed);
  if(todo.length){const old=clone(project.state);project=await api('/projects/'+project.id+'/captions/review',{method:'POST',body:JSON.stringify({revision:project.revision,caption_ids:todo.map(c=>c.id)})});remember(old);draw();}
  await downloadSavedFile(`/api/projects/${project.id}/captions.srt`,(project.name||'자막')+'.srt');});
render();
})();
