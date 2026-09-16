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

    const socket = useRef(null);
    const currentAudio = useRef(null);

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
            };

            audio.onerror = () => {
                setSpeaking(false);
                URL.revokeObjectURL(url);

                if (currentAudio.current === audio) {
                    currentAudio.current = null;
                }
            };

            audio.play().catch((error) => {
                console.error('Audio playback failed:', error);
                setSpeaking(false);
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

            if (data.type === 'message_complete') {
                setMessages((items) => [
                    ...items,
                    {
                        role: 'assistant',
                        text: data.message
                    }
                ]);
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

            ws.close();
        };
    }, []);

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