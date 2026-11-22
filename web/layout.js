/* 4칸 편집 화면: 왼쪽 채팅(+작업실), 가운데 영상, 아래 편집 툴바·타임라인, 오른쪽 편집 지침.
   기존 요소(아이디·버튼 동작)는 그대로 두고 위치만 옮긴다. 좁은 화면에서는 위아래로 쌓인다. */
(function(){
const main=document.querySelector('main');if(!main||main.classList.contains('studio-grid'))return;
const q=s=>document.querySelector(s);
const col=cls=>{const d=document.createElement('div');d.className=cls;return d;};
const left=col('studio-left'),center=col('studio-center'),right=col('studio-right');
const library=q('aside.library'),chat=q('#chat-panel');
const toolbar=q('.workspace-toolbar'),viewer=q('section.viewer'),timeline=q('section.timeline');
const library_box=document.createElement('details');library_box.className='library-box';library_box.open=true;
library_box.innerHTML='<summary>내 작업실 · 영상 불러오기</summary>';
if(library){library_box.appendChild(library);left.appendChild(library_box);}
[toolbar,viewer,timeline].forEach(e=>e&&center.appendChild(e));
// 오른쪽은 '1. 편집 지침 / 2. 편집 채팅' 두 탭으로 나눈다
const tabs=document.createElement('div');tabs.className='rail-tabs';tabs.setAttribute('role','tablist');
tabs.innerHTML='<button type="button" role="tab" data-rail="story">1. 영상 콘티</button><button type="button" role="tab" data-rail="guide">2. 편집 지침</button><button type="button" role="tab" data-rail="chat">3. 편집 채팅</button><button type="button" role="tab" data-rail="caption">4. 캡션 자막</button>';
const storyPane=col('rail-pane rail-story'),guidePane=col('rail-pane rail-guide'),chatPane=col('rail-pane rail-chat'),capPane=col('rail-pane rail-caption');
capPane.innerHTML='<section class="panel cap-panel"><div class="cap-actions"><button type="button" id="cap-generate" class="primary">생성</button><button type="button" id="cap-srt" class="secondary">SRT 다운로드</button></div><div id="cap-list" class="cap-list"></div></section>';
storyPane.innerHTML='<section class="panel story-panel"><div class="story-head"><h2>영상 콘티</h2><span id="storyboard-status" class="muted"></span></div><p class="muted">후킹, 녹음 대본, 편집 구성표를 붙여 넣으세요. 프로젝트마다 저장되고, 구성표의 목표 길이(예: 목표 65초)는 자동 편집에 반영돼요.</p><textarea id="storyboard-text" maxlength="20000" placeholder="예) 프리미엄 가나 초콜릿 4종 비교 숏폼&#10;시식 순서: CU 소금우유 → GS25 호지차 → …&#10;목표 65초"></textarea></section>';
right.append(tabs,storyPane,guidePane,chatPane,capPane);if(chat)chatPane.appendChild(chat);
const showRail=name=>{right.dataset.rail=name;tabs.querySelectorAll('button').forEach(b=>{const on=b.dataset.rail===name;b.classList.toggle('active',on);b.setAttribute('aria-selected',on);});
  storyPane.hidden=name!=='story';guidePane.hidden=name!=='guide';chatPane.hidden=name!=='chat';capPane.hidden=name!=='caption';try{localStorage.setItem('studio-rail',name);}catch{}
  if(name==='chat')setTimeout(()=>q('#chat-input')?.focus(),0);};
tabs.addEventListener('click',e=>{const b=e.target.closest('[data-rail]');if(b)showRail(b.dataset.rail);});
let firstRail='story';try{const saved=localStorage.getItem('studio-rail');if(['story','guide','chat','caption'].includes(saved))firstRail=saved;}catch{}
showRail(firstRail);window.showRail=showRail;
// 작업 공간에 남은 나머지(지침 자동 편집, 대본 편집, 무음 편집, 작업 진행, 기획판, 세부 편집)는 원래 순서대로 오른쪽으로
const workspace=q('section.workspace'),grid=q('.editor-grid');
const rest=[...(workspace?.children||[])].flatMap(e=>e===grid?[...grid.children]:[e]).filter(e=>e!==toolbar&&e!==viewer&&e!==timeline);
rest.forEach(e=>guidePane.appendChild(e));
// 편집 지침 탭: 영상 유형·화면 선택을 맨 위로, 화면은 '영상 화면 / 9:16 화면' 버튼으로
{const g=s=>guidePane.querySelector(s),styleSel=g('#guided-style'),frameSel=g('#guided-frame'),text=g('#guided-text');
  const top=document.createElement('div');top.className='guide-top';
  const styleLabel=styleSel?.closest('label'),frameLabel=frameSel?.closest('label');
  if(styleLabel)top.appendChild(styleLabel);
  if(frameSel){const box=document.createElement('div');box.className='frame-toggle';box.innerHTML='<button type="button" data-frame="auto">영상 화면</button><button type="button" data-frame="fill">9:16 화면</button>';
    const sync=()=>box.querySelectorAll('[data-frame]').forEach(b=>b.classList.toggle('active',b.dataset.frame===(frameSel.value==='fill'?'fill':'auto')));
    box.addEventListener('click',e=>{const b=e.target.closest('[data-frame]');if(!b)return;frameSel.value=b.dataset.frame;frameSel.dispatchEvent(new Event('change',{bubbles:true}));sync();});
    frameSel.addEventListener('change',sync);sync();frameLabel.hidden=true;top.appendChild(box);top.appendChild(frameLabel);}
  const textLabel=text?.closest('label');if(textLabel)textLabel.before(top);
  const capBtn=g('#guided-captions');if(capBtn)capBtn.hidden=true;}
const assets=library?.querySelector('#assets')||q('#assets');
if(timeline&&assets){const media=document.createElement('div');media.className='media-row';
  media.innerHTML='<div class="media-head"><b>영상 <span id="media-count">0개</span></b><span class="media-add"><label class="button secondary" title="영상 파일 추가">＋ 영상 추가<input type="file" id="timeline-upload" accept="video/*,.mkv,.mov,.mp4" multiple hidden></label><label class="button ghost" title="폴더 안 영상을 모두 추가">📁 폴더 추가<input type="file" id="timeline-upload-folder" webkitdirectory directory multiple hidden></label></span></div>';
  media.appendChild(assets);const head=timeline.querySelector('.timeline-heading');head?head.after(media):timeline.prepend(media);}
// 자동 편집 시작·추천 재생·최종 다운로드 버튼은 재생 막대 오른쪽 끝으로
const transport=viewer?.querySelector('.transport');
if(transport){const acts=document.createElement('div');acts.className='transport-actions';
  ['guided-start','guided-play','guided-download'].forEach(id=>{const b=guidePane.querySelector('#'+id)||q('#'+id);if(b)acts.appendChild(b);});
  if(acts.children.length)transport.appendChild(acts);}
// 타임라인 제목은 편집 도구 아래(트랙 바로 위)로
const tlHead=timeline?.querySelector('.timeline-heading'),tlTools=timeline?.querySelector('.edit-tools');
if(tlHead&&tlTools)tlTools.after(tlHead);
// 왼쪽 아래: 단축키 모음
const keys=document.createElement('div');keys.className='shortcut-card';
keys.innerHTML='<b>단축키<span id="app-version"></span></b><dl>'+[['Space','재생'],['B','자르기 도구'],['A','선택 도구'],['E','여기서 자르기'],['Q','왼쪽 삭제'],['W','오른쪽 삭제'],['Del','삭제'],['빈 곳 끌기','여러 개 선택'],['Ctrl+A','전체 선택'],['Ctrl+D','복제'],['Ctrl+Z','취소'],['Ctrl+Y','다시'],['Ctrl+C','복사'],['Ctrl+V','붙여넣기'],['Ctrl+X','잘라내기'],['[ ]','구간 이동'],['← →','1프레임'],['Shift+← →','1초'],['↑ ↓','이전·다음 컷'],['휠','좌우 이동'],['Alt+휠','위아래 줄'],['Ctrl+휠','확대·축소']].map(([k,v])=>`<dt><kbd>${k}</kbd></dt><dd>${v}</dd>`).join('')+'</dl>';
left.appendChild(keys);
const old=[...main.children];
main.append(left,center,right);
// 타임라인은 가운데와 오른쪽 아래를 가로질러 넓게
if(timeline){timeline.classList.add('studio-bottom');main.appendChild(timeline);}
old.forEach(e=>{if(e!==left&&e!==center&&e!==right&&!e.children.length)e.remove();else if(e.classList?.contains('workspace'))e.hidden=true;});
main.classList.add('studio-grid');document.body.classList.add('studio');
// 작업실 접힘 상태는 이 브라우저에 기억한다(채팅 공간을 넓히고 싶을 때 접기)
try{if(localStorage.getItem('studio-library-open')==='0')library_box.open=false;}catch{}
library_box.addEventListener('toggle',()=>{try{localStorage.setItem('studio-library-open',library_box.open?'1':'0');}catch{}});
// 화면 높이에서 머리글(과 위쪽 안내 줄)만큼 빼서 타임라인이 아래로 잘리지 않게 한다
const fit=()=>{const h=Math.max(0,Math.round(main.getBoundingClientRect().top+scrollY));document.documentElement.style.setProperty('--hdr',(h||70)+'px');};
fit();addEventListener('resize',fit);
if(window.ResizeObserver){const ro=new ResizeObserver(fit);[q('header'),q('#desktop-setup')].forEach(e=>e&&ro.observe(e));}
})();
