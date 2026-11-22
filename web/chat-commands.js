/* 무료 편집 채팅: 정해진 한국어 표현을 편집 명령으로 바꾼다(인터넷·유료 API 없음).
   parseCommand(text) → {kind, refs, seconds, side, ...}. 실제 편집은 chat.js가 한다.
   refs: 컷 번호(1부터). 'L' = 마지막 컷, 'S' = 지금 선택한 컷, 'ALL' = 모든 컷. */
(function(root){
const ORD={'첫':1,'한':1,'하나':1,'두':2,'둘':2,'세':3,'셋':3,'네':4,'넷':4,'다섯':5,'여섯':6,'일곱':7,'여덟':8,'아홉':9,'열':10};
const NUMWORD=Object.keys(ORD).sort((a,b)=>b.length-a.length).join('|');

function normalize(text){
  let t=String(text||'').trim().replace(/\s+/g,' ').toLowerCase();
  t=t.replace(new RegExp(`(${NUMWORD})\\s*번\\s*째`,'g'),(_,w)=>ORD[w]+'번');
  t=t.replace(/(\d+)\s*번\s*째/g,'$1번');
  t=t.replace(/첫\s*(컷|구간|장면)/g,'1번 $1');
  t=t.replace(/(맨\s*)?마지막\s*(컷|구간|장면|번)/g,'L번 ');
  t=t.replace(/(지금|선택한|선택된|이)\s*(컷|구간|장면|거|것)/g,'S번 ');
  t=t.replace(/(모든|전체|전부의?)\s*(컷|구간|장면)(들)?|컷\s*전부|전부\s*다/g,'ALL번 ');
  t=t.replace(/반\s*초/g,'0.5초').replace(/(\d+)\s*점\s*(\d+)\s*초/g,'$1.$2초');
  return t;
}

function seconds(t){
  // "1분 20초", "0.5초", "300ms", "3프레임"(→ frames)
  let m=t.match(/(\d+)\s*분\s*(\d+(?:\.\d+)?)\s*초/);if(m)return {value:+m[1]*60+ +m[2]};
  m=t.match(/(\d+(?:\.\d+)?)\s*초/);if(m)return {value:+m[1]};
  m=t.match(/(\d+)\s*(ms|밀리초)/);if(m)return {value:+m[1]/1000};
  m=t.match(/(\d+)\s*프레임/);if(m)return {frames:+m[1]};
  m=t.match(/(\d+)\s*분/);if(m)return {value:+m[1]*60};
  return null;
}

function refs(t){
  const s=t.replace(/\d+\s*분\s*\d+(?:\.\d+)?\s*초|\d+(?:\.\d+)?\s*초|\d+\s*(ms|밀리초|프레임|분)/g,' ');
  const out=[];
  const range=/(\d+|L)\s*번?\s*(?:~|-|부터|에서)\s*(\d+|L)\s*번(?:\s*까지)?/g;let m,rest=s;
  while((m=range.exec(s))){out.push({from:m[1],to:m[2]});rest=rest.replace(m[0],' ');}
  const one=/(\d+|L|S|ALL)\s*번/g;
  while((m=one.exec(rest)))out.push(m[1]);
  return out;
}

const V={
  del:/(지워|지우|삭제|없애|날려|제거|빼\s*줘|빼$|빼고|빼라|빼자|버려)/,
  extend:/(늘려|늘리|늘여|늘이|길게|연장|더\s*(넣|붙|길)|추가)/,
  shorten:/(줄여|줄이|짧게|잘라\s*내|잘라내|깎|당겨|덜어|빼)/,
  head:/(앞|시작|처음|머리|앞쪽|앞부분|도입)/,
  tail:/(끝|뒤|뒷|꼬리|뒤쪽|뒷부분|말끝|마무리)/,
  both:/(양쪽|앞뒤|앞\s*뒤|양\s*끝)/,
  split:/(잘라|자르|분할|나눠|나누|쪼개|컷\s*나눠)/,
  move:/(옮겨|옮기|이동|보내|가져|넣어|위치)/,
};

function parseCommand(text){
  const raw=String(text||'');const t=normalize(raw);
  if(!t)return {kind:'empty'};
  const sec=seconds(t),r=refs(t);
  if(/^(\?|도움|도움말|명령어|사용법|help)|뭐\s*(할\s*수|되|돼)|어떻게\s*(써|사용)/.test(t))return {kind:'help'};
  if(/다시\s*실행|redo|되살려|취소\s*(한\s*거\s*)?다시|ctrl\s*\+?\s*y/.test(t))return {kind:'redo'};
  if(/되돌려|되돌리|실행\s*취소|원래대로|방금\s*(거\s*)?취소|ctrl\s*\+?\s*z|^취소/.test(t))return {kind:'undo'};
  if(/(몇\s*개|길이\s*(가|는)?\s*(얼마|몇)|총\s*(길이|몇)|얼마나\s*(길|돼)|현재\s*상태|상태\s*알려)/.test(t)&&!V.del.test(t))return {kind:'info'};
  if(/srt|자막\s*(파일|받|다운|저장)/.test(t))return {kind:'export',what:'srt'};
  if(/(mp4|내보내|렌더|영상\s*(저장|받|다운)|최종\s*(저장|다운|영상)|다운로드)/.test(t))return {kind:'export',what:'mp4'};
  if(/무음/.test(t)&&/(빼|제거|자동|정리|잘라|없애|지워|편집|컷)/.test(t))return {kind:'silence'};
  const style=(t.match(/(해석|영화|드라마|애니|먹방|원테이크|레시피|요리|맛집|식당|브이로그|현장|체험|일상)/)||[])[1];
  if(style&&/(스타일|유형|모드|로\s*(바꿔|해|설정)|으로\s*(바꿔|해|설정))/.test(t))return {kind:'style',style,start:/편집\s*(해|시작|돌려)/.test(t)};
  if(/(자동\s*편집|지침\s*대로|지시문\s*대로|다시\s*편집|편집\s*(다시\s*)?(해\s*줘|시작|돌려))/.test(t)&&!r.length)return {kind:'guided',style:style||null};
  if(/(멈춰|멈추|정지|스톱|stop|그만\s*재생|일시\s*정지)/.test(t))return {kind:'pause'};
  if(/(재생|틀어|플레이|play|보여\s*줘\s*처음)/.test(t))return {kind:'play',ref:r[0]??(/처음부터|맨\s*처음/.test(t)?'1':null),from:/처음부터|맨\s*처음/.test(t)?0:null};
  if(sec&&!r.length&&/(로|으로|에|지점)?\s*(가|이동|옮겨|점프|넘어가|가\s*줘)/.test(t)&&!V.extend.test(t)&&!V.shorten.test(t))return {kind:'seek',seconds:sec};
  if(/(여기|지금\s*위치|재생\s*위치|현재\s*위치)/.test(t)){
    if(V.split.test(t)&&!/(앞|뒤)/.test(t))return {kind:'split',ref:'S',here:true};
    if(/(앞|왼쪽)/.test(t)&&(V.del.test(t)||V.shorten.test(t)||/잘라/.test(t)))return {kind:'trimHere',side:'head'};
    if(/(뒤|오른쪽)/.test(t)&&(V.del.test(t)||V.shorten.test(t)||/잘라/.test(t)))return {kind:'trimHere',side:'tail'};
  }
  if(/(합쳐|합치|하나로|이어\s*붙여|붙여서\s*하나)/.test(t))return {kind:'merge',refs:r};
  if(/(바꿔|교체|자리\s*(를\s*)?바|순서\s*바)/.test(t)&&r.length>=2)return {kind:'swap',refs:r};
  const toStart=/(맨\s*앞|맨\s*처음|처음\s*으로|첫\s*번째로|앞\s*으로\s*(보내|옮)|1번\s*자리)/.test(t);
  const toEnd=/(맨\s*뒤|맨\s*끝|끝\s*으로|마지막\s*으로|뒤\s*로\s*(보내|옮))/.test(t);
  const rel=t.match(/(\d+|L)\s*번\s*(?:컷|구간)?\s*(앞|뒤|다음)\s*(?:에|으로|로)?/);
  if(V.move.test(t)||toStart||toEnd){
    if(rel&&r.length>=2)return {kind:'move',refs:[r[0]],to:rel[2]==='앞'?'before':'after',target:rel[1]};
    if(toStart&&r.length)return {kind:'move',refs:[r[0]],to:'start'};
    if(toEnd&&r.length)return {kind:'move',refs:[r[0]],to:'end'};
  }
  if(/(복제|하나\s*더|복사해서\s*붙|똑같이\s*하나|두\s*번\s*넣)/.test(t))return {kind:'duplicate',refs:r.length?r:['S']};
  if(V.split.test(t)&&!/잘라\s*내|잘라내/.test(t)&&(/초\s*(지점)?\s*(에서|에)|반\s*으로|절반|가운데|중간/.test(t)||!sec)){
    const at=/반\s*으로|절반|가운데|중간/.test(t)?'middle':sec;
    return {kind:'split',ref:r[0]||'S',at:at||null,here:!at};
  }
  if(sec&&(V.extend.test(t)||V.shorten.test(t))){
    const grow=V.extend.test(t)&&!/(줄여|줄이|짧게)/.test(t);
    const side=V.both.test(t)?'both':V.head.test(t)?'head':'tail';
    return {kind:'resize',refs:r.length?r:['S'],seconds:sec,side,grow};
  }
  const shorter=t.match(/(\d+(?:\.\d+)?)\s*초\s*(보다|미만|이하|안\s*되는|도\s*안\s*되는)?\s*(짧은|작은|미만)/);
  if(shorter&&V.del.test(t))return {kind:'deleteShort',under:+shorter[1]};
  if(V.del.test(t))return {kind:'delete',refs:r.length?r:['S']};
  if(r.length&&/(선택|보여|가\s*줘|가자|봐|열어|찾아|이동|확인)/.test(t))return {kind:'select',ref:r[0]};
  if(r.length===1&&/^\s*(\d+|L)\s*번\s*(컷|구간)?\s*$/.test(t))return {kind:'select',ref:r[0]};
  return {kind:'unknown'};
}

const HELP=[
  '3번 컷 지워 · 2~4번 삭제 · 마지막 컷 빼줘 · 1초보다 짧은 컷 지워',
  '3번 끝 0.3초 늘려 · 2번 앞 0.5초 줄여 · 모든 컷 끝 0.2초 늘려',
  '3번이랑 5번 바꿔 · 4번 맨 앞으로 · 2번을 5번 뒤로 옮겨',
  '여기서 잘라 · 3번 반으로 나눠 · 3번 2초에서 잘라 · 여기 앞 지워',
  '3번이랑 4번 합쳐 · 3번 복제',
  '재생 · 멈춰 · 처음부터 재생 · 3번부터 재생 · 20초로 가',
  '되돌려 · 다시 실행 · 몇 개야?',
  '무음 빼줘 · 해석 스타일로 바꿔 · 자동 편집 해줘 · MP4 저장 · SRT 받기',
];
root.parseCommand=parseCommand;root.CHAT_HELP=HELP;
if(typeof module!=='undefined')module.exports={parseCommand,HELP,normalize};
})(typeof window!=='undefined'?window:globalThis);
