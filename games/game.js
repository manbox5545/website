import * as THREE from "three";

const scene=new THREE.Scene();
scene.background=new THREE.Color(0x87CEEB);

const camera=new THREE.PerspectiveCamera(
70,
window.innerWidth/window.innerHeight,
0.1,
1000
);

const renderer=new THREE.WebGLRenderer({antialias:true});

renderer.setSize(window.innerWidth,window.innerHeight);
renderer.shadowMap.enabled=true;

document.body.appendChild(renderer.domElement);

// Sun

const light=new THREE.DirectionalLight(0xffffff,2);
light.position.set(20,40,10);
light.castShadow=true;
scene.add(light);

scene.add(new THREE.AmbientLight(0xffffff,.6));

// Ground

const ground=new THREE.Mesh(

new THREE.PlaneGeometry(300,300),

new THREE.MeshLambertMaterial({color:0x55aa55})

);

ground.rotation.x=-Math.PI/2;
ground.receiveShadow=true;
scene.add(ground);

// Road

const road=new THREE.Mesh(

new THREE.BoxGeometry(12,.1,300),

new THREE.MeshStandardMaterial({color:0x444444})

);

road.position.y=.05;

scene.add(road);

// Houses

const houses=[];

for(let i=0;i<20;i++){

const h=new THREE.Mesh(

new THREE.BoxGeometry(5,5,5),

new THREE.MeshLambertMaterial({
color:Math.random()*0xffffff
})

);

h.position.set(

Math.random()>0.5?15:-15,

2.5,

-140+i*15

);

scene.add(h);

houses.push(h);

}

// Trees

for(let i=0;i<40;i++){

const trunk=new THREE.Mesh(

new THREE.CylinderGeometry(.3,.3,2),

new THREE.MeshLambertMaterial({color:0x8b5a2b})

);

trunk.position.set(

(Math.random()-0.5)*80,

1,

(Math.random()-0.5)*250

);

scene.add(trunk);

const leaves=new THREE.Mesh(

new THREE.SphereGeometry(1.5),

new THREE.MeshLambertMaterial({color:0x228B22})

);

leaves.position.copy(trunk.position);

leaves.position.y=3;

scene.add(leaves);

}

// Cycle

const bike=new THREE.Group();

const frame=new THREE.Mesh(

new THREE.BoxGeometry(.3,.3,2),

new THREE.MeshStandardMaterial({color:0x2196f3})

);

bike.add(frame);

const wheelGeo=new THREE.TorusGeometry(.5,.1,16,50);

const wheelMat=new THREE.MeshStandardMaterial({color:0x222});

const w1=new THREE.Mesh(wheelGeo,wheelMat);
w1.rotation.y=Math.PI/2;
w1.position.z=.8;

const w2=w1.clone();
w2.position.z=-.8;

bike.add(w1);
bike.add(w2);

bike.position.y=.6;

scene.add(bike);

camera.position.set(0,6,-10);

let speed=0;
let money=0;
let carrying=false;

const keys={};

document.addEventListener("keydown",e=>keys[e.key]=true);
document.addEventListener("keyup",e=>keys[e.key]=false);

// Package

const packageBox=new THREE.Mesh(

new THREE.BoxGeometry(.6,.6,.6),

new THREE.MeshLambertMaterial({color:0x996633})

);

packageBox.position.set(0,.4,-120);

scene.add(packageBox);

function animate(){

requestAnimationFrame(animate);

if(keys["w"]) speed=.25;
else if(keys["s"]) speed=-.15;
else speed*=.95;

if(keys["a"]) bike.rotation.y+=.04;
if(keys["d"]) bike.rotation.y-=.04;

bike.position.x-=Math.sin(bike.rotation.y)*speed;
bike.position.z-=Math.cos(bike.rotation.y)*speed;

camera.position.lerp(

new THREE.Vector3(

bike.position.x,

6,

bike.position.z-8

),

.1

);

camera.lookAt(bike.position);

if(!carrying &&
bike.position.distanceTo(packageBox.position)<2){

carrying=true;

bike.add(packageBox);

packageBox.position.set(0,1,-1);

document.getElementById("packages").innerHTML=1;

}

if(carrying){

houses.forEach(h=>{

if(bike.position.distanceTo(h.position)<4){

money+=100;

document.getElementById("money").innerHTML=money;

document.getElementById("packages").innerHTML=0;

carrying=false;

bike.remove(packageBox);

packageBox.position.set(

0,

.4,

-120-Math.random()*100

);

scene.add(packageBox);

}

});

}

renderer.render(scene,camera);

}

animate();

window.addEventListener("resize",()=>{

camera.aspect=window.innerWidth/window.innerHeight;

camera.updateProjectionMatrix();

renderer.setSize(window.innerWidth,window.innerHeight);

});