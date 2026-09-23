import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { createElement, Maximize, ZoomIn, ZoomOut } from 'lucide';

const $ = id => document.getElementById(id);
for (const [id, icon] of [['fit', Maximize], ['zoomIn', ZoomIn], ['zoomOut', ZoomOut]]) {
  $(id).append(createElement(icon));
}
const cache = new Map();
let current = 'symbol', generation = 0, renderer, scene, camera, controls, model;
let scale = 1, offset = {x:0, y:0}, drag;
function status(text, error=false) { $('status').textContent=text; $('status').classList.toggle('error',error); }
async function request(route) {
  const response = await fetch(route);
  if (!response.ok) throw new Error('미리보기 앱과 연결할 수 없습니다. 앱에서 다시 열어 주세요.');
  const data = await response.json();
  if (data.error) throw new Error(data.error);
  return data;
}
function transform() { $('image').style.transform=`translate(${offset.x}px,${offset.y}px) scale(${scale})`; }
function fit() {
  if (current !== 'model') { scale=1; offset={x:0,y:0}; transform(); return; }
  if (!model) return;
  const box = new THREE.Box3().setFromObject(model);
  const size=box.getSize(new THREE.Vector3()), center=box.getCenter(new THREE.Vector3());
  const radius=Math.max(size.length()/2, 0.001);
  const vertical=THREE.MathUtils.degToRad(camera.fov/2);
  const horizontal=Math.atan(Math.tan(vertical)*camera.aspect);
  const distance=radius/Math.sin(Math.min(vertical,horizontal))*1.15;
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(1,1,1).normalize().multiplyScalar(distance));
  camera.near=radius/1000; camera.far=radius*1000;
  camera.updateProjectionMatrix(); controls.minDistance=radius*0.05; controls.maxDistance=radius*100;
  controls.update();
}
function zoom(factor) {
  if (current==='model' && controls) {
    camera.position.sub(controls.target).multiplyScalar(factor).add(controls.target); controls.update();
  } else { scale=Math.max(0.2,Math.min(20,scale/factor)); transform(); }
}
function init3d() {
  if (renderer) return;
  renderer=new THREE.WebGLRenderer({antialias:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio,2));
  renderer.setClearColor(0xf0f2f4);
  renderer.toneMapping=THREE.ACESFilmicToneMapping;
  $('scene').append(renderer.domElement);
  scene=new THREE.Scene();
  camera=new THREE.PerspectiveCamera(40,1,0.001,1000);
  controls=new OrbitControls(camera,renderer.domElement);
  controls.enableDamping=true;
  scene.add(new THREE.HemisphereLight(0xffffff,0x667078,2.6));
  for (const pos of [[3,5,4],[-3,2,-4]]) {
    const light=new THREE.DirectionalLight(0xffffff,3); light.position.set(...pos); scene.add(light);
  }
  new ResizeObserver(() => {
    const {width,height}=$('scene').getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width,height); camera.aspect=width/height; camera.updateProjectionMatrix();
  }).observe($('scene'));
  renderer.setAnimationLoop(() => {
    if (current==='model') { controls.update(); renderer.render(scene,camera); }
  });
}
async function show(kind) {
  current=kind; const ticket=++generation;
  document.querySelectorAll('[data-kind]').forEach(b => b.setAttribute('aria-selected',String(b.dataset.kind===kind)));
  $('image').hidden=true; $('scene').hidden=true; $('pages').hidden=true;
  status('미리보기 생성 중...');
  try {
    if (!cache.has(kind)) cache.set(kind,request(kind));
    const data=await cache.get(kind);
    if (ticket!==generation) return;
    if (kind==='model') {
      $('scene').hidden=false; init3d();
      const {width,height}=$('scene').getBoundingClientRect();
      renderer.setSize(width,height); camera.aspect=width/height;
      if (!model) {
        const bytes=Uint8Array.from(atob(data.pages[0].data),c=>c.charCodeAt(0));
        const gltf=await new GLTFLoader().parseAsync(bytes.buffer,'');
        if (ticket!==generation) return;
        model=gltf.scene;
        let meshes=0; model.traverse(n=>{if(n.isMesh) meshes++;});
        if (!meshes) { model=null; throw new Error('표시할 3D 형상이 없습니다. STEP 모델 연결을 확인해 주세요.'); }
        scene.add(model);
      }
      fit();
    } else {
      $('pages').replaceChildren(...data.pages.map((p,i)=>new Option(p.name,i)));
      $('pages').hidden=data.pages.length<2;
      page(data.pages[0]);
    }
    status('');
  } catch(e) {
    cache.delete(kind);
    if(ticket===generation) status(e.message,true);
  }
}
function page(item) { $('image').src='data:image/svg+xml;base64,'+item.data; $('image').hidden=false; fit(); }
$('pages').onchange=async()=>page((await cache.get(current)).pages[$('pages').value]);
$('fit').onclick=fit; $('zoomIn').onclick=()=>zoom(0.8); $('zoomOut').onclick=()=>zoom(1.25);
$('image').addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.1:1/1.1);},{passive:false});
$('image').onpointerdown=e=>{drag={x:e.clientX-offset.x,y:e.clientY-offset.y};e.target.setPointerCapture(e.pointerId);};
$('image').onpointermove=e=>{if(drag){offset={x:e.clientX-drag.x,y:e.clientY-drag.y};transform();}};
$('image').onpointerup=$('image').onpointercancel=()=>{drag=null;};
document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>show(b.dataset.kind));
request('part').then(p=>{$('name').textContent=p.symbol;$('footprint').textContent=p.footprint;document.title=p.symbol+' - 파트 미리보기';}).catch(e=>status(e.message,true));
show('symbol');
