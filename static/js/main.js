let ws = null;
let audioContext = null;
let mediaStream = null;
let processor = null;
let isConnected = false;

// DOM Elements
const connectionDot = document.getElementById('connection-dot');
const connectionStatus = document.getElementById('connection-status');
const chatContainer = document.getElementById('chat-container');
const micBtn = document.getElementById('mic-btn');
const micText = document.getElementById('mic-text');
const orbContainer = document.getElementById('orb-container');
const aiStatus = document.getElementById('ai-status');

let currentAssistantMessageDiv = null;

function setOrbState(state) {
    orbContainer.className = 'orb-container';
    if (state !== 'idle') {
        orbContainer.classList.add(state);
    }
    aiStatus.textContent = state.charAt(0).toUpperCase() + state.slice(1);
}

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function createMessageDiv(role) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    return div;
}

function appendMessage(role, content) {
    const div = createMessageDiv(role);
    div.textContent = content;
    chatContainer.appendChild(div);
    scrollToBottom();
}

async function connectToGemini() {
    if (isConnected) return;
    
    micBtn.classList.add('calling');
    micText.textContent = 'Connecting...';
    
    try {
        // 1. Get Microphone access
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true
        }});
        
        // 2. Initialize AudioContext at 16kHz
        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        
        // 3. Setup WebSocket
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
        ws.binaryType = 'arraybuffer';
        
        ws.onopen = () => {
            isConnected = true;
            connectionDot.className = 'dot connected';
            connectionStatus.textContent = 'Connected to Gemini Live';
            
            micBtn.classList.remove('calling');
            micBtn.classList.add('active');
            micBtn.classList.add('in-call');
            micText.textContent = 'End Call';
            setOrbState('listening');
            
            startRecording();
        };
        
        ws.onmessage = (event) => {
            if (event.data instanceof ArrayBuffer) {
                playAudioChunk(event.data);
            } else {
                handleJSONMessage(JSON.parse(event.data));
            }
        };
        
        ws.onclose = () => {
            disconnect();
        };
        
    } catch (e) {
        console.error("Failed to connect", e);
        micBtn.classList.remove('calling');
        micText.textContent = 'Call Receptionist';
        alert("Failed to connect: " + e.message);
    }
}

let nextPlayTime = 0;

function playAudioChunk(arrayBuffer) {
    if (arrayBuffer.byteLength % 2 !== 0) {
        console.warn("Odd byte length, slicing...");
        arrayBuffer = arrayBuffer.slice(0, arrayBuffer.byteLength - 1);
    }
    const int16Array = new Int16Array(arrayBuffer);
    const float32Array = new Float32Array(int16Array.length);
    for (let i = 0; i < int16Array.length; i++) {
        float32Array[i] = int16Array[i] / 32768.0;
    }
    
    // Gemini outputs at 24kHz
    const audioBuffer = audioContext.createBuffer(1, float32Array.length, 24000);
    audioBuffer.getChannelData(0).set(float32Array);
    
    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);
    
    const currentTime = audioContext.currentTime;
    if (nextPlayTime < currentTime) {
        nextPlayTime = currentTime;
    }
    source.start(nextPlayTime);
    nextPlayTime += audioBuffer.duration;
}

function startRecording() {
    const source = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);
    
    source.connect(processor);
    processor.connect(audioContext.destination);
    
    processor.onaudioprocess = (e) => {
        if (!isConnected || ws.readyState !== WebSocket.OPEN) return;
        
        const rawInputData = e.inputBuffer.getChannelData(0);
        const inputSampleRate = audioContext.sampleRate;
        
        // Resample if browser ignored our 16000 request (common on Linux/Mac)
        let inputData = rawInputData;
        if (inputSampleRate !== 16000) {
            const ratio = inputSampleRate / 16000;
            const newLength = Math.floor(rawInputData.length / ratio);
            inputData = new Float32Array(newLength);
            for (let i = 0; i < newLength; i++) {
                inputData[i] = rawInputData[Math.floor(i * ratio)];
            }
        }
        
        // Convert Float32 to Int16
        const pcmData = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
            let s = Math.max(-1, Math.min(1, inputData[i]));
            pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        
        ws.send(pcmData.buffer);
    };
}

function handleJSONMessage(data) {
    if (data.type === 'transcript') {
        setOrbState('idle');
        appendMessage('user', data.content);
        const welcome = document.querySelector('.welcome-message');
        if (welcome) welcome.style.display = 'none';
    } 
    else if (data.type === 'status') {
        setOrbState('thinking');
    }
    else if (data.type === 'transcript_chunk') {
        setOrbState('speaking');
        if (!currentAssistantMessageDiv) {
            currentAssistantMessageDiv = createMessageDiv('assistant');
            chatContainer.appendChild(currentAssistantMessageDiv);
        }
        currentAssistantMessageDiv.textContent += data.content;
        scrollToBottom();
    }
    else if (data.type === 'transcript_complete') {
        if (!currentAssistantMessageDiv) {
            currentAssistantMessageDiv = createMessageDiv('assistant');
            chatContainer.appendChild(currentAssistantMessageDiv);
        }
        if (data.content) {
            currentAssistantMessageDiv.textContent = data.content;
        }
        currentAssistantMessageDiv = null;
        scrollToBottom();
        setOrbState('listening');
    }
    else if (data.type === 'end_call') {
        disconnect();
    }
}

function disconnect() {
    if (!isConnected) return;
    isConnected = false;
    
    if (ws) {
        ws.close();
        ws = null;
    }
    
    if (processor) {
        processor.disconnect();
        processor = null;
    }
    
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    
    connectionDot.className = 'dot disconnected';
    connectionStatus.textContent = 'Disconnected';
    
    micBtn.classList.remove('active');
    micBtn.classList.remove('in-call');
    micBtn.classList.remove('calling');
    micText.textContent = 'Call Receptionist';
    setOrbState('idle');
}

micBtn.addEventListener('click', () => {
    if (isConnected) {
        disconnect();
    } else {
        connectToGemini();
    }
});
