// LiveKit WebRTC implementation
let room;
let isConnected = false;

// DOM Elements
const connectionDot = document.getElementById('connection-dot');
const connectionStatus = document.getElementById('connection-status');
const chatContainer = document.getElementById('chat-container');
const micBtn = document.getElementById('mic-btn');
const micText = document.getElementById('mic-text');
const orbContainer = document.getElementById('orb-container');
const aiStatus = document.getElementById('ai-status');

// Helper to update orb
function setOrbState(state) {
    orbContainer.className = 'orb-container';
    if (state !== 'idle') {
        orbContainer.classList.add(state);
    }
    aiStatus.textContent = state.charAt(0).toUpperCase() + state.slice(1);
}

// Helper to scroll
function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
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

let currentAssistantMessageDiv = null;

async function connectToLiveKit() {
    if (isConnected) return;
    
    micBtn.classList.add('calling');
    micText.textContent = 'Connecting...';
    
    try {
        // Fetch token from backend
        const response = await fetch('/api/token');
        const data = await response.json();
        const token = data.token;
        const livekitUrl = data.url;
        
        room = new LivekitClient.Room({
            adaptiveStream: true,
            dynacast: true,
            audioCaptureDefaults: {
                autoGainControl: true,
                echoCancellation: true,
                noiseSuppression: true,
            }
        });
        
        // Handle incoming data messages (UI updates from Python)
        room.on(LivekitClient.RoomEvent.DataReceived, (payload, participant, kind, topic) => {
            const strData = new TextDecoder().decode(payload);
            try {
                const msg = JSON.parse(strData);
                handleJSONMessage(msg);
            } catch (e) {
                console.error("Failed parsing data", e);
            }
        });
        
        // Handle incoming audio tracks (AI speaking)
        room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, publication, participant) => {
            if (track.kind === LivekitClient.Track.Kind.Audio) {
                const element = track.attach();
                document.body.appendChild(element);
            }
        });

        // Wait for connection to established
        await room.connect(livekitUrl, token);
        
        // Turn on the microphone and publish the stream to the room!
        await room.localParticipant.setMicrophoneEnabled(true);
        
        isConnected = true;
        
        connectionDot.className = 'dot connected';
        connectionStatus.textContent = 'Connected via LiveKit WebRTC';
        
        micBtn.classList.remove('calling');
        micBtn.classList.add('active');
        micBtn.classList.add('in-call');
        micText.textContent = 'End Call';
        setOrbState('listening');

    } catch (e) {
        console.error("Failed to connect to LiveKit", e);
        micBtn.classList.remove('calling');
        micText.textContent = 'Call Receptionist';
        alert("Failed to connect: " + e.message);
    }
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
        currentAssistantMessageDiv.textContent = data.content;
        currentAssistantMessageDiv = null;
        scrollToBottom();
        
        // Once AI finishes speaking, go back to listening
        setOrbState('listening');
    }
    else if (data.type === 'end_call') {
        disconnect();
    }
}

async function disconnect() {
    if (!isConnected) return;
    
    await room.disconnect();
    isConnected = false;
    
    connectionDot.className = 'dot disconnected';
    connectionStatus.textContent = 'Disconnected';
    
    micBtn.classList.remove('active');
    micBtn.classList.remove('in-call');
    micBtn.classList.remove('calling');
    micText.textContent = 'Call Receptionist';
    setOrbState('idle');
}

// Setup Event Listeners
micBtn.addEventListener('click', () => {
    if (isConnected) {
        disconnect();
    } else {
        connectToLiveKit();
    }
});
