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
if(chat)left.appendChild(chat);
[toolbar,viewer,timeline].forEach(e=>e&&center.appendChild(e));
const rightHead=document.createElement('div');rightHead.className='rail-head';rightHead.innerHTML='<h2>편집 지침</h2>';
right.appendChild(rightHead);
// 작업 공간에 남은 나머지(지침 자동 편집, 대본 편집, 무음 편집, 작업 진행, 기획판, 세부 편집)는 원래 순서대로 오른쪽으로
const workspace=q('section.workspace'),grid=q('.editor-grid');
const rest=[...(workspace?.children||[])].flatMap(e=>e===grid?[...grid.children]:[e]).filter(e=>e!==toolbar&&e!==viewer&&e!==timeline);
rest.forEach(e=>right.appendChild(e));
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
