import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// Configuration & WebSocket Target
const BACKEND_HTTP = 'https://fyp-demo-production-5c42.up.railway.app';
const BACKEND_WS = 'wss://fyp-demo-production-5c42.up.railway.app/ws/seats';

// Seat Color Palettes (Vacant = Emerald Green, Occupied = Crimson Red)
const COLOR_VACANT = new THREE.Color(0x10b981);
const COLOR_OCCUPIED = new THREE.Color(0xef4444);
const EMISSIVE_VACANT = new THREE.Color(0x044f35);
const EMISSIVE_OCCUPIED = new THREE.Color(0x610a0a);

// State Data Store
const seatObjects = {};
const seatData = {
  1: { id: 1, name: "Seat A (Left)", state: "VACANT", targetColor: COLOR_VACANT, targetEmissive: EMISSIVE_VACANT },
  2: { id: 2, name: "Seat B (Center)", state: "VACANT", targetColor: COLOR_VACANT, targetEmissive: EMISSIVE_VACANT },
  3: { id: 3, name: "Seat C (Right)", state: "VACANT", targetColor: COLOR_VACANT, targetEmissive: EMISSIVE_VACANT }
};

// -------------------------------------------------------------
// 1. THREE.JS SCENE SETUP
// -------------------------------------------------------------
const container = document.getElementById('canvas-container');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x090c15);
scene.fog = new THREE.FogExp2(0x090c15, 0.035);

const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, 6, 10);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
container.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.maxPolarAngle = Math.PI / 2 - 0.02; // Don't clip below floor
controls.minDistance = 3;
controls.maxDistance = 20;

// -------------------------------------------------------------
// 2. LIGHTING & ENVIRONMENT
// -------------------------------------------------------------
const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
scene.add(ambientLight);

const mainDirectional = new THREE.DirectionalLight(0xffffff, 1.2);
mainDirectional.position.set(5, 12, 8);
mainDirectional.castShadow = true;
mainDirectional.shadow.mapSize.width = 2048;
mainDirectional.shadow.mapSize.height = 2048;
mainDirectional.shadow.camera.near = 0.5;
mainDirectional.shadow.camera.far = 25;
mainDirectional.shadow.camera.left = -8;
mainDirectional.shadow.camera.right = 8;
mainDirectional.shadow.camera.top = 8;
mainDirectional.shadow.camera.bottom = -8;
scene.add(mainDirectional);

// Floor Grid & Platform
const floorGeo = new THREE.PlaneGeometry(30, 30);
const floorMat = new THREE.MeshStandardMaterial({
  color: 0x111827,
  roughness: 0.8,
  metalness: 0.2
});
const floor = new THREE.Mesh(floorGeo, floorMat);
floor.rotation.x = -Math.PI / 2;
floor.receiveShadow = true;
scene.add(floor);

const gridHelper = new THREE.GridHelper(30, 30, 0x3b82f6, 0x1f2937);
gridHelper.position.y = 0.01;
scene.add(gridHelper);

// -------------------------------------------------------------
// 3. CHAIR 3D MESH GENERATOR
// -------------------------------------------------------------
function createChairMesh(seatId, xPos) {
  const chairGroup = new THREE.Group();
  chairGroup.position.set(xPos, 0, 0);

  // Materials
  const baseFrameMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.5, metalness: 0.8 });
  const cushionMat = new THREE.MeshStandardMaterial({
    color: COLOR_VACANT.clone(),
    emissive: EMISSIVE_VACANT.clone(),
    emissiveIntensity: 0.4,
    roughness: 0.4,
    metalness: 0.1
  });

  // Seat Cushion
  const cushionGeo = new THREE.BoxGeometry(1.4, 0.25, 1.3);
  const cushionMesh = new THREE.Mesh(cushionGeo, cushionMat);
  cushionMesh.position.set(0, 0.75, 0);
  cushionMesh.castShadow = true;
  cushionMesh.receiveShadow = true;
  chairGroup.add(cushionMesh);

  // Backrest
  const backrestGeo = new THREE.BoxGeometry(1.4, 1.2, 0.2);
  const backrestMesh = new THREE.Mesh(backrestGeo, cushionMat);
  backrestMesh.position.set(0, 1.45, -0.55);
  backrestMesh.castShadow = true;
  backrestMesh.receiveShadow = true;
  chairGroup.add(backrestMesh);

  // Chair Base Pedestal / Legs
  const legGeo = new THREE.CylinderGeometry(0.06, 0.06, 0.65, 16);
  const legPositions = [
    [-0.55, 0.32, -0.5],
    [0.55, 0.32, -0.5],
    [-0.55, 0.32, 0.5],
    [0.55, 0.32, 0.5]
  ];
  legPositions.forEach(([lx, ly, lz]) => {
    const leg = new THREE.Mesh(legGeo, baseFrameMat);
    leg.position.set(lx, ly, lz);
    leg.castShadow = true;
    chairGroup.add(leg);
  });

  // Seat Zone Base Ring / Pedestal Glow
  const ringGeo = new THREE.RingGeometry(0.9, 1.1, 32);
  const ringMat = new THREE.MeshBasicMaterial({
    color: COLOR_VACANT.clone(),
    side: THREE.DoubleSide,
    transparent: true,
    opacity: 0.8
  });
  const ringMesh = new THREE.Mesh(ringGeo, ringMat);
  ringMesh.rotation.x = -Math.PI / 2;
  ringMesh.position.set(0, 0.02, 0);
  chairGroup.add(ringMesh);

  // Dedicated Spotlight above seat
  const spotLight = new THREE.SpotLight(COLOR_VACANT.getHex(), 3.0, 8, Math.PI / 4, 0.5);
  spotLight.position.set(xPos, 4.5, 0);
  spotLight.target = chairGroup;
  spotLight.castShadow = true;
  scene.add(spotLight);

  scene.add(chairGroup);

  seatObjects[seatId] = {
    group: chairGroup,
    cushionMat: cushionMat,
    ringMat: ringMat,
    spotLight: spotLight
  };
}

// Build 3 chairs
createChairMesh(1, -3.5);
createChairMesh(2, 0.0);
createChairMesh(3, 3.5);

// -------------------------------------------------------------
// 4. WEBSOCKET & STATE MANAGEMENT
// -------------------------------------------------------------
function updateUIAnd3D(seatsList) {
  let occupiedCount = 0;
  let vacantCount = 0;

  seatsList.forEach(seat => {
    const sid = seat.id;
    const isOccupied = (seat.state === "OCCUPIED");

    if (isOccupied) occupiedCount++;
    else vacantCount++;

    // Update internal targets for Three.js lerp
    if (seatData[sid]) {
      seatData[sid].state = seat.state;
      seatData[sid].targetColor = isOccupied ? COLOR_OCCUPIED : COLOR_VACANT;
      seatData[sid].targetEmissive = isOccupied ? EMISSIVE_OCCUPIED : EMISSIVE_VACANT;
    }

    // Update DOM UI Cards
    const cardEl = document.getElementById(`seat-card-${sid}`);
    const pillEl = document.getElementById(`seat-pill-${sid}`);
    const timeEl = document.getElementById(`seat-time-${sid}`);

    if (cardEl && pillEl) {
      if (isOccupied) {
        cardEl.className = "glass-panel seat-card occupied";
        pillEl.className = "seat-status-pill occupied";
        pillEl.textContent = "OCCUPIED";
      } else {
        cardEl.className = "glass-panel seat-card vacant";
        pillEl.className = "seat-status-pill vacant";
        pillEl.textContent = "VACANT";
      }
    }
    if (timeEl) {
      timeEl.textContent = new Date().toLocaleTimeString();
    }
  });

  // Update Global Counter Badges
  const occVal = document.getElementById('occupied-seats-val');
  const vacVal = document.getElementById('vacant-seats-val');
  if (occVal) occVal.textContent = occupiedCount;
  if (vacVal) vacVal.textContent = vacantCount;
}

function initWebSocket() {
  const statusBadge = document.getElementById('connection-status');
  const statusText = document.getElementById('status-text');

  console.log(`Connecting to WebSocket: ${BACKEND_WS}`);
  const ws = new WebSocket(BACKEND_WS);

  ws.onopen = () => {
    console.log("WebSocket connection established!");
    if (statusBadge && statusText) {
      statusBadge.querySelector('.dot').className = 'dot green';
      statusText.textContent = 'LIVE WEBSOCKET';
    }
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "SNAPSHOT" || msg.type === "SEAT_UPDATE") {
        updateUIAnd3D(msg.data);
      }
    } catch (e) {
      console.error("Error parsing WebSocket message:", e);
    }
  };

  ws.onerror = (err) => {
    console.warn("WebSocket error:", err);
  };

  ws.onclose = () => {
    console.warn("WebSocket connection lost. Reconnecting in 3s...");
    if (statusBadge && statusText) {
      statusBadge.querySelector('.dot').className = 'dot red';
      statusText.textContent = 'RECONNECTING...';
    }
    setTimeout(initWebSocket, 3000);
  };
}

// Manual Toggle helper attached to window for testing buttons
window.toggleSeat = async (seatId) => {
  try {
    const res = await fetch(`${BACKEND_HTTP}/api/seats/${seatId}/toggle`, { method: 'POST' });
    const data = await res.json();
    console.log("Toggled seat:", data);
  } catch (e) {
    console.error("Failed to toggle seat via REST API:", e);
  }
};

// -------------------------------------------------------------
// 5. ANIMATION LOOP & COLOR SMOOTH LERPING
// -------------------------------------------------------------
function animate() {
  requestAnimationFrame(animate);

  controls.update();

  // Smooth lerp for material color changes
  for (let sid = 1; sid <= 3; sid++) {
    const target = seatData[sid];
    const obj = seatObjects[sid];
    if (target && obj) {
      obj.cushionMat.color.lerp(target.targetColor, 0.08);
      obj.cushionMat.emissive.lerp(target.targetEmissive, 0.08);
      obj.ringMat.color.lerp(target.targetColor, 0.08);
      obj.spotLight.color.lerp(target.targetColor, 0.08);
    }
  }

  renderer.render(scene, camera);
}

// Window Resize Handler
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// Start
initWebSocket();
animate();
