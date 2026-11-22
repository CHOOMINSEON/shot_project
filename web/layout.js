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
tabs.innerHTML='<button type="button" role="tab" data-rail="guide">1. 편집 지침</button><button type="button" role="tab" data-rail="chat">2. 편집 채팅</button>';
const guidePane=col('rail-pane rail-guide'),chatPane=col('rail-pane rail-chat');
right.append(tabs,guidePane,chatPane);if(chat)chatPane.appendChild(chat);
const showRail=name=>{right.dataset.rail=name;tabs.querySelectorAll('button').forEach(b=>{const on=b.dataset.rail===name;b.classList.toggle('active',on);b.setAttribute('aria-selected',on);});
  guidePane.hidden=name!=='guide';chatPane.hidden=name!=='chat';try{localStorage.setItem('studio-rail',name);}catch{}
  if(name==='chat')setTimeout(()=>q('#chat-input')?.focus(),0);};
tabs.addEventListener('click',e=>{const b=e.target.closest('[data-rail]');if(b)showRail(b.dataset.rail);});
let firstRail='guide';try{firstRail=localStorage.getItem('studio-rail')==='chat'?'chat':'guide';}catch{}
showRail(firstRail);window.showRail=showRail;
// 작업 공간에 남은 나머지(지침 자동 편집, 대본 편집, 무음 편집, 작업 진행, 기획판, 세부 편집)는 원래 순서대로 오른쪽으로
const workspace=q('section.workspace'),grid=q('.editor-grid');
const rest=[...(workspace?.children||[])].flatMap(e=>e===grid?[...grid.children]:[e]).filter(e=>e!==toolbar&&e!==viewer&&e!==timeline);
rest.forEach(e=>guidePane.appendChild(e));
const assets=library?.querySelector('#assets')||q('#assets');
if(timeline&&assets){const media=document.createElement('div');media.className='media-row';
  media.innerHTML='<div class="media-head"><b>영상 <span id="media-count">0개</span></b><span class="media-add"><label class="button secondary" title="영상 파일 추가">＋ 영상 추가<input type="file" id="timeline-upload" accept="video/*,.mkv,.mov,.mp4" multiple hidden></label><label class="button ghost" title="폴더 안 영상을 모두 추가">📁 폴더 추가<input type="file" id="timeline-upload-folder" webkitdirectory directory multiple hidden></label></span></div>';
  media.appendChild(assets);const head=timeline.querySelector('.timeline-heading');head?head.after(media):timeline.prepend(media);}
const old=[...main.children];
main.append(left,center,right);
old.forEach(e=>{if(e!==left&&e!==center&&e!==right&&!e.children.length)e.remove();else if(e.classList?.contains('workspace'))e.hidden=true;});
main.classList.add('studio-grid');document.body.classList.add('studio');
// 작업실 접힘 상태는 이 브라우저에 기억한다(채팅 공간을 넓히고 싶을 때 접기)
try{if(localStorage.getItem('studio-library-open')==='0')library_box.open=false;}catch{}
library_box.addEventListener('toggle',()=>{try{localStorage.setItem('studio-library-open',library_box.open?'1':'0');}catch{}});
const fit=()=>{const h=q('header')?.offsetHeight||70;document.documentElement.style.setProperty('--hdr',h+'px');};
fit();addEventListener('resize',fit);
})();
