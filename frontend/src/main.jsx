import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const API = 'http://localhost:8000';

function App() {
    const [messages, setMessages] = useState([
        {
            role: 'assistant',
            text: 'Ada yang bisa saya bantu?'
        }
    ]);

    const [text, setText] = useState('');
    const [events, setEvents] = useState([]);
    const [tools, setTools] = useState([]);
    const [memory, setMemory] = useState([]);
    const [permission, setPermission] = useState(null);
    const [pendingMessage, setPendingMessage] = useState('');
    const [online, setOnline] = useState(false);
    const [speaking, setSpeaking] = useState(false);
    const [voiceMode, setVoiceMode] = useState(false);
    const [voiceStatus, setVoiceStatus] = useState('Pause');
    const [status, setStatus] = useState('');
    const [streamingText, setStreamingText] = useState('');

    const socket = useRef(null);
    const currentAudio = useRef(null);
    const microphone = useRef(null);
    const audioContext = useRef(null);
    const microphoneSource = useRef(null);
    const microphoneProcessor = useRef(null);
    const pcmCarry = useRef(new Int16Array(0));
    const voiceReady = useRef(false);
    const voiceModeRef = useRef(false);

    const stopMicrophone = () => {
        microphoneProcessor.current?.disconnect();
        microphoneSource.current?.disconnect();
        microphoneProcessor.current = null;
        microphoneSource.current = null;
        audioContext.current?.close();
        audioContext.current = null;
        microphone.current?.getTracks().forEach((track) => track.stop());
        microphone.current = null;
        pcmCarry.current = new Int16Array(0);
    };

    const sendPcm = (samples) => {
        if (socket.current?.readyState !== WebSocket.OPEN) return;
        const bytes = new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength);
        let binary = '';
        bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
        socket.current.send(JSON.stringify({ type: 'voice_audio', audio: btoa(binary) }));
    };

    const startMicrophone = async () => {
        if (!voiceModeRef.current || microphone.current) return;
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
            });
            if (!voiceModeRef.current) {
                stream.getTracks().forEach((track) => track.stop());
                return;
            }
            const context = new AudioContext();
            const source = context.createMediaStreamSource(stream);
            const processor = context.createScriptProcessor(4096, 1, 1);
            microphone.current = stream;
            audioContext.current = context;
            microphoneSource.current = source;
            microphoneProcessor.current = processor;
            processor.onaudioprocess = (event) => {
                const input = event.inputBuffer.getChannelData(0);
                const ratio = context.sampleRate / 16000;
                const converted = new Int16Array(Math.floor(input.length / ratio));
                for (let index = 0; index < converted.length; index += 1) {
                    const value = input[Math.min(Math.floor(index * ratio), input.length - 1)];
                    converted[index] = Math.max(-1, Math.min(1, value)) * 32767;
                }
                const pending = new Int16Array(pcmCarry.current.length + converted.length);
                pending.set(pcmCarry.current);
                pending.set(converted, pcmCarry.current.length);
                let offset = 0;
                while (offset + 512 <= pending.length) {
                    sendPcm(pending.slice(offset, offset + 512));
                    offset += 512;
                }
                pcmCarry.current = pending.slice(offset);
            };
            source.connect(processor);
            processor.connect(context.destination);
            setVoiceStatus('Mendengarkan...');
        } catch (error) {
            const denied = error?.name === 'NotAllowedError' || error?.name === 'SecurityError';
            setVoiceStatus(denied ? 'BERU belum mendapat izin microphone.' : 'Microphone tidak tersedia.');
            socket.current?.send(JSON.stringify({ type: 'voice_mode', enabled: false }));
            voiceModeRef.current = false;
            setVoiceMode(false);
        }
    };

    const addEvent = (event) => {
        setEvents((items) => [
            {
                time: new Date().toLocaleTimeString(),
                ...event
            },
            ...items
        ].slice(0, 50));
    };

    const playAudio = (base64, mimeType = 'audio/mpeg') => {
        try {
            // Hentikan audio sebelumnya
            if (currentAudio.current) {
                currentAudio.current.pause();
                currentAudio.current.src = '';
                currentAudio.current = null;
            }

            const audioData = atob(base64);

            const bytes = new Uint8Array(audioData.length);

            for (let i = 0; i < audioData.length; i++) {
                bytes[i] = audioData.charCodeAt(i);
            }

            const blob = new Blob(
                [bytes],
                { type: mimeType }
            );

            const url = URL.createObjectURL(blob);

            const audio = new Audio(url);

            currentAudio.current = audio;

            setSpeaking(true);

            audio.onended = () => {
                setSpeaking(false);
                URL.revokeObjectURL(url);

                if (currentAudio.current === audio) {
                    currentAudio.current = null;
                }
                if (voiceModeRef.current) {
                    socket.current?.send(JSON.stringify({ type: 'voice_playback_finished' }));
                }
            };

            audio.onerror = () => {
                setSpeaking(false);
                URL.revokeObjectURL(url);

                if (currentAudio.current === audio) {
                    currentAudio.current = null;
                }
                if (voiceModeRef.current) {
                    socket.current?.send(JSON.stringify({ type: 'voice_playback_finished' }));
                }
            };

            audio.play().catch((error) => {
                console.error('Audio playback failed:', error);
                setSpeaking(false);
                if (voiceModeRef.current) {
                    socket.current?.send(JSON.stringify({ type: 'voice_playback_finished' }));
                }
            });

        } catch (error) {
            console.error('Failed to decode TTS audio:', error);
            setSpeaking(false);
        }
    };

    useEffect(() => {
        fetch(API + '/tools')
            .then((response) => response.json())
            .then(setTools)
            .catch(() => {});

        fetch(API + '/memory')
            .then((response) => response.json())
            .then(setMemory)
            .catch(() => {});

        const ws = new WebSocket(
            'ws://localhost:8000/ws/chat'
        );

        socket.current = ws;

        ws.onopen = () => {
            setOnline(true);
        };

        ws.onclose = () => {
            setOnline(false);
        };

        ws.onerror = () => {
            setOnline(false);
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);

            addEvent(data);

            if (data.type === 'thinking') {
                setStatus(data.status || 'Memproses...');
                if (voiceModeRef.current) setVoiceStatus('Memproses...');
            }

            if (data.type === 'tool_started') {
                setStatus(data.status || 'Menjalankan tool...');
            }

            if (data.type === 'message_delta') {
                setStreamingText((current) => current + (data.delta || ''));
            }

            if (data.type === 'message_complete') {
                setMessages((items) => [
                    ...items,
                    {
                        role: 'assistant',
                        text: data.message
                    }
                ]);
                setStreamingText('');
                setStatus('');
            }

            if (data.type === 'voice_ready') {
                voiceReady.current = true;
                startMicrophone();
            }

            if (data.type === 'voice_listening') {
                if (data.status && voiceReady.current) startMicrophone();
                if (data.status) setVoiceStatus('Mendengarkan...');
            }

            if (data.type === 'voice_recording' && data.status) {
                setVoiceStatus('Merekam...');
            }

            if (data.type === 'voice_recording' && !data.status) {
                stopMicrophone();
                setVoiceStatus('Memproses...');
            }

            if (data.type === 'transcript') {
                setMessages((items) => [...items, { role: 'user', text: data.text }]);
                setVoiceStatus('Memproses...');
            }

            if (data.type === 'voice_speaking' && data.status) {
                stopMicrophone();
                setVoiceStatus('BERU berbicara...');
            }

            if (data.type === 'stt_error' || data.type === 'voice_error') {
                setVoiceStatus(data.message);
            }

            if (data.type === 'permission_required') {
                setPendingMessage(
                    data.message || pendingMessage
                );

                setPermission(data);
            }

            if (data.type === 'tts_started') {
                setSpeaking(true);
            }

            if (data.type === 'tts_audio') {
                playAudio(
                    data.audio,
                    data.mime_type || 'audio/mpeg'
                );
            }

            if (data.type === 'tts_finished') {
                // Audio tetap dibiarkan berjalan sampai selesai.
            }

            if (data.type === 'tts_error') {
                setSpeaking(false);

                console.error(
                    'BERU TTS error:',
                    data.message
                );
            }
        };

        return () => {
            if (currentAudio.current) {
                currentAudio.current.pause();
            }

            stopMicrophone();

            ws.close();
        };
    }, []);

    const toggleVoiceMode = () => {
        const enabled = !voiceModeRef.current;
        voiceModeRef.current = enabled;
        setVoiceMode(enabled);
        voiceReady.current = false;
        if (!enabled) {
            stopMicrophone();
            setVoiceStatus('Pause');
            socket.current?.send(JSON.stringify({ type: 'voice_mode', enabled: false }));
            return;
        }
        if (!navigator.mediaDevices?.getUserMedia) {
            setVoiceStatus('Microphone tidak tersedia.');
            voiceModeRef.current = false;
            setVoiceMode(false);
            return;
        }
        setVoiceStatus('Menyiapkan microphone...');
        socket.current?.send(JSON.stringify({ type: 'voice_mode', enabled: true }));
        socket.current?.send(JSON.stringify({ type: 'voice_start' }));
    };

    const send = (approved = false) => {
        const message = approved
            ? pendingMessage
            : text;

        if (
            !message.trim() ||
            socket.current?.readyState !== WebSocket.OPEN
        ) {
            return;
        }

        if (!approved) {
            setMessages((items) => [
                ...items,
                {
                    role: 'user',
                    text: message
                }
            ]);

            setPendingMessage(message);
        }

        socket.current.send(
            JSON.stringify({
                message,
                approved
            })
        );

        setText('');
        setPermission(null);

        if (approved) {
            setPendingMessage('');
        }
    };

    return (
        <main>
            <header>
                <b>BERU</b>

                <span
                    className={
                        online
                            ? 'online'
                            : 'offline'
                    }
                >
                    ● {online ? 'ONLINE' : 'OFFLINE'}
                </span>

                {speaking && (
                    <span className="speaking">
                        🔊 BERU sedang berbicara
                    </span>
                )}
                <button className="voice-toggle" onClick={toggleVoiceMode} disabled={!online}>
                    {voiceMode ? 'VOICE MODE: ON' : 'VOICE MODE: OFF'}
                </button>
            </header>

            <section className="layout">

                <aside>
                    <h2>◉ BERU</h2>

                    <nav>
                        Dashboard
                        <br />
                        Chat
                        <br />
                        Tools
                        <br />
                        Memory
                        <br />
                        Activity
                        <br />
                        Settings
                    </nav>

                    <h3>Tools</h3>

                    {tools.map((tool) => (
                        <small key={tool.name}>
                            ⚙ {tool.name} · {tool.permission}
                        </small>
                    ))}
                </aside>

                <article>
                    <h1>BERU AI</h1>

                    {status && <small className="status">{status}</small>}
                    <div className={`voice-status ${voiceMode ? 'active' : ''}`}>
                        🎤 {voiceStatus}
                    </div>

                    <div className="chat">
                        {messages.map((message, index) => (
                            <p
                                key={index}
                                className={message.role}
                            >
                                <label>
                                    {message.role === 'user'
                                        ? 'YOU'
                                        : 'BERU'}
                                </label>

                                {message.text}
                            </p>
                        ))}
                        {streamingText && (
                            <p className="assistant streaming">
                                <label>BERU</label>
                                {streamingText}
                            </p>
                        )}
                    </div>

                    {permission && (
                        <div className="permission">
                            <b>
                                ⚠ BERU wants to run{' '}
                                {permission.tool}
                            </b>

                            <code>
                                {JSON.stringify(
                                    permission.arguments
                                )}
                            </code>

                            <button
                                onClick={() => send(true)}
                            >
                                Allow once
                            </button>

                            <button
                                onClick={() => {
                                    setPermission(null);
                                    setPendingMessage('');
                                }}
                            >
                                Cancel
                            </button>
                        </div>
                    )}

                    <form
                        onSubmit={(event) => {
                            event.preventDefault();

                            if (!text.trim()) {
                                return;
                            }

                            send();
                        }}
                    >
                        <input
                            value={text}
                            onChange={(event) =>
                                setText(event.target.value)
                            }
                            placeholder="Speak or type to BERU..."
                        />

                        <button type="submit">
                            ➤
                        </button>
                    </form>
                </article>

                <aside className="activity">
                    <h3>Activity</h3>

                    {events.map((event, index) => (
                        <p key={index}>
                            <time>
                                {event.time}
                            </time>{' '}
                            {String(event.type || '')
                                .replaceAll('_', ' ')}
                        </p>
                    ))}

                    <h3>Memory</h3>

                    {memory.map((item) => (
                        <small key={item.key}>
                            {item.key}: {item.value}
                        </small>
                    ))}
                </aside>

            </section>

            <footer>
                CPU / RAM live metrics are available
                through BERU system tools · Network{' '}
                <span className="online">●</span>
            </footer>
        </main>
    );
}

createRoot(
    document.getElementById('root')
).render(
    <App />
);
