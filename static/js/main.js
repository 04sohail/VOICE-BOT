let ws;
let mediaRecorder;
let audioChunks = [];
let audioContext;
let isRecording = false;

// DOM Elements
const connectionDot = document.getElementById('connection-dot');
const connectionStatus = document.getElementById('connection-status');
const chatContainer = document.getElementById('chat-container');
const micBtn = document.getElementById('mic-btn');
const micText = document.getElementById('mic-text');
const orbContainer = document.getElementById('orb-container');
const aiStatus = document.getElementById('ai-status');

// Web Audio API
const initAudioContext = () => {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContext.state === 'suspended') {
        audioContext.resume();
    }
};

// WebSocket Connection
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        connectionDot.className = 'dot connected';
        connectionStatus.textContent = 'Connected';
    };

    ws.onclose = () => {
        connectionDot.className = 'dot disconnected';
        connectionStatus.textContent = 'Disconnected';
        setTimeout(connectWebSocket, 3000);
    };

    ws.onmessage = async (event) => {
        if (event.data instanceof Blob) {
            // Received audio binary data
            playAudioData(event.data);
        } else {
            try {
                const data = JSON.parse(event.data);
                handleJSONMessage(data);
            } catch (e) {
                console.error("Failed to parse WS message", e);
            }
        }
    };
}

let currentAssistantMessageDiv = null;

function handleJSONMessage(data) {
    if (data.type === 'transcript') {
        setOrbState('idle');
        appendMessage('user', data.content);
        // Reset welcome message if present
        const welcome = document.querySelector('.welcome-message');
        if (welcome) welcome.style.display = 'none';
    } 
    else if (data.type === 'status') {
        setOrbState('thinking');
    }
    else if (data.type === 'transcript_chunk') {
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
        currentAssistantMessageDiv.textContent = data.content;
        currentAssistantMessageDiv = null;
        scrollToBottom();
    }
    else if (data.type === 'audio_start') {
        setOrbState('speaking');
    }
    else if (data.type === 'audio_end') {
        // Handled after audio playback finishes
    }
}

let audioQueue = [];
let isPlayingAudio = false;

let currentAudioSource = null;

async function playNextInQueue() {
    if (audioQueue.length === 0) {
        isPlayingAudio = false;
        setOrbState('idle');
        return;
    }
    
    isPlayingAudio = true;
    const blob = audioQueue.shift();
    
    try {
        initAudioContext();
        const arrayBuffer = await blob.arrayBuffer();
        
        if (arrayBuffer.byteLength === 0) {
            playNextInQueue();
            return;
        }

        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
        currentAudioSource = audioContext.createBufferSource();
        currentAudioSource.buffer = audioBuffer;
        currentAudioSource.connect(audioContext.destination);
        
        currentAudioSource.onended = () => {
            currentAudioSource = null;
            playNextInQueue();
        };
        
        currentAudioSource.start(0);
        setOrbState('speaking');
    } catch (e) {
        console.error("Error playing audio chunk", e);
        currentAudioSource = null;
        playNextInQueue();
    }
}

async function playAudioData(blob) {
    audioQueue.push(blob);
    if (!isPlayingAudio) {
        playNextInQueue();
    }
}

// UI Helpers
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

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function setOrbState(state) {
    orbContainer.className = 'orb-container';
    if (state !== 'idle') {
        orbContainer.classList.add(state);
    }
    aiStatus.textContent = state.charAt(0).toUpperCase() + state.slice(1);
}

let silenceTimer;
let isUserSpeaking = false;
let analyser;
let dataArray;
let detectSoundFrame;
let consecutiveSpeechFrames = 0;

function interruptAI() {
    if (currentAudioSource) {
        currentAudioSource.stop();
        currentAudioSource = null;
    }
    audioQueue = [];
    isPlayingAudio = false;
    
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "interrupt" }));
    }
}

async function toggleRecording() {
    if (isRecording) {
        stopRecording();
        return;
    }
    
    try {
        initAudioContext();
        const stream = await navigator.mediaDevices.getUserMedia({ 
            audio: { noiseSuppression: true, echoCancellation: true, autoGainControl: true } 
        });
        
        analyser = audioContext.createAnalyser();
        const microphone = audioContext.createMediaStreamSource(stream);
        microphone.connect(analyser);
        analyser.fftSize = 512;
        dataArray = new Uint8Array(analyser.frequencyBinCount);
        
        mediaRecorder = new MediaRecorder(stream, { 
            mimeType: 'audio/webm;codecs=opus',
            audioBitsPerSecond: 128000
        });
        audioChunks = [];
        
        let isFlushing = false;
        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
                // Keep a ~600ms sliding window of audio BEFORE speech is detected
                // CRITICAL: We splice index 1, explicitly preserving index 0 (the WebM EBML header!)
                if (!isUserSpeaking && audioChunks.length > 6) {
                    audioChunks.splice(1, 1);
                }
            }
        };
        
        mediaRecorder.onstop = () => {
            if (audioChunks.length <= 1) { 
                audioChunks = [];
                if (isRecording) mediaRecorder.start(100);
                return; 
            }
            
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            const reader = new FileReader();
            reader.readAsArrayBuffer(audioBlob);
            reader.onloadend = () => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(reader.result);
                    setOrbState('thinking');
                }
            };
            audioChunks = [];
            
            // Restart the recorder to generate a fresh header for the next sentence
            if (isRecording) {
                mediaRecorder.start(100);
            }
        };
        
        // Start recording continuously in 100ms chunks
        mediaRecorder.start(100);
        isRecording = true;
        setOrbState('listening');
        micBtn.classList.add('active');
        micText.textContent = 'Stop Listening';
        
        detectSound();
        
    } catch (e) {
        console.error("Microphone access denied", e);
        alert("Please allow microphone access.");
    }
}

function detectSound() {
    if (!isRecording) return;
    
    const pcmData = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(pcmData);
    
    let sumSquares = 0.0;
    for (const amplitude of pcmData) {
        sumSquares += amplitude * amplitude;
    }
    const rms = Math.sqrt(sumSquares / pcmData.length);
    
    // Dynamic threshold: If the AI is currently talking out loud, the microphone will pick it up (speaker echo).
    // To prevent the AI from interrupting itself, we require a much louder sound (0.06) to interrupt it.
    // If the room is quiet, the normal speaking threshold (0.02) applies.
    let dynamicThreshold = isPlayingAudio ? 0.08 : 0.02;
    
    if (rms > dynamicThreshold) { 
        consecutiveSpeechFrames++;
        // Needs ~80ms (5 frames) of continuous loud sound to trigger speech, 
        // preventing sharp noises (clicks, coughs) from interrupting.
        if (consecutiveSpeechFrames > 5) {
            if (!isUserSpeaking) {
                isUserSpeaking = true;
                console.log("🎤 Speech detected: Started recording.");
                setOrbState('listening');
                interruptAI(); // Stop AI from talking instantly
                // Note: mediaRecorder is already running and capturing the pre-speech buffer!
            }
            
            clearTimeout(silenceTimer);
            silenceTimer = setTimeout(() => {
                if (isUserSpeaking) {
                    isUserSpeaking = false;
                    console.log("🛑 Silence detected: Stopped recording and sending audio.");
                    if (mediaRecorder && mediaRecorder.state === "recording") {
                        // This triggers onstop, which sends the blob and instantly restarts it
                        mediaRecorder.stop(); 
                    }
                }
            }, 800); // 800ms of silence = end of speech
        }
    } else {
        consecutiveSpeechFrames = 0;
    }
    detectSoundFrame = requestAnimationFrame(detectSound);
}

function stopRecording() {
    if (!isRecording) return;
    cancelAnimationFrame(detectSoundFrame);
    if (mediaRecorder) {
        mediaRecorder.stream.getTracks().forEach(t => t.stop());
        mediaRecorder.stop();
    }
    isRecording = false;
    isUserSpeaking = false;
    clearTimeout(silenceTimer);
    micBtn.classList.remove('active');
    micText.textContent = 'Start Listening';
    setOrbState('idle');
}

// Setup Event Listeners
micBtn.addEventListener('click', toggleRecording);

// Init
connectWebSocket();
