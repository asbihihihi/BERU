"""BERU voice assistant Windows. Salin .env.example menjadi .env."""
from __future__ import annotations
import asyncio,json,logging,os,queue,re,shutil,subprocess,tempfile,time,webbrowser
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus,urlparse
from zoneinfo import ZoneInfo
import edge_tts,numpy as np,psutil,requests,sounddevice as sd,torch
from dotenv import load_dotenv
from scipy.io.wavfile import write

ROOT=Path(__file__).parent; RATE=16000; BLOCK=512; LOG=logging.getLogger("BERU")
GROQ="https://api.groq.com/openai/v1/audio/transcriptions"
PROMPT="Bahasa Indonesia. BERU. Perintah komputer: buka tutup jalankan cuaca waktu cmd powershell chrome edge firefox steam photoshop vscode visual studio code task manager file explorer phone link calculator youtube google github ping ipconfig python php laravel composer npm git."
@dataclass(frozen=True)
class Config:
 key:str;host:str;model:str;location:str;lat:float;lon:float;voice:str;tts_rate:str;tts_volume:str;tts_pitch:str;device:int|str|None;threshold:float;silence:float;minimum:float
 @property
 def chat(self): return self.host.rstrip("/")+"/api/chat"
def setup_logging(): logging.basicConfig(level=logging.INFO,format="[%(name)s] %(message)s")
def create_temp_path(prefix:str,suffix:str)->Path:
 """Buat path temporer dan segera tutup descriptor mkstemp (wajib di Windows)."""
 fd,name=tempfile.mkstemp(prefix=prefix,suffix=suffix)
 os.close(fd)
 return Path(name)
def cleanup_temp_file(path:Path,attempts:int=5)->None:
 """Hapus temporary file setelah pemilik resource dilepas; retry hanya safety net."""
 for attempt in range(attempts):
  try:path.unlink();return
  except FileNotFoundError:return
  except PermissionError as exc:
   if attempt==attempts-1:LOG.error("[SYSTEM] Gagal membersihkan file temporer %s: %s",path,exc);return
   time.sleep(.1*(attempt+1))
def load_config()->Config:
 env=ROOT/".env";load_dotenv(env)
 if not env.exists():raise RuntimeError("File .env tidak ditemukan. Salin .env.example menjadi .env.")
 key=os.getenv("GROQ_API_KEY","").strip()
 if not key or key=="YOUR_GROQ_API_KEY":raise RuntimeError("GROQ_API_KEY kosong di .env.")
 d=os.getenv("MICROPHONE_DEVICE","").strip();dev=int(d) if d.lstrip("-").isdigit() else d or None
 try:return Config(key,os.getenv("OLLAMA_HOST","http://localhost:11434"),os.getenv("OLLAMA_MODEL","qwen2.5:3b"),os.getenv("DEFAULT_LOCATION","Purwokerto"),float(os.getenv("DEFAULT_LATITUDE","-7.4242")),float(os.getenv("DEFAULT_LONGITUDE","109.2396")),os.getenv("TTS_VOICE","id-ID-ArdiNeural"),os.getenv("TTS_RATE","-5%"),os.getenv("TTS_VOLUME","+0%"),os.getenv("TTS_PITCH","+0Hz"),dev,float(os.getenv("VAD_THRESHOLD",".55")),float(os.getenv("SILENCE_TIMEOUT",".85")),float(os.getenv("MIN_RECORD_SECONDS",".8")))
 except ValueError as e:raise RuntimeError(f"Konfigurasi .env tidak valid: {e}") from e
def check_ollama(c):
 try:
  r=requests.get(c.host.rstrip("/")+"/api/tags",timeout=3);r.raise_for_status()
  if c.model not in {x.get("name") for x in r.json().get("models",[])}:LOG.warning("[LLM] Model belum ada: ollama pull %s",c.model)
  return True
 except requests.RequestException:LOG.error("[LLM] Ollama tidak berjalan di %s",c.host);return False
def initialize_vad():
 try:torch.set_num_threads(1);m,_=torch.hub.load("snakers4/silero-vad","silero_vad",trust_repo=True);m.eval();return m
 except Exception as e:raise RuntimeError(f"Gagal memuat Silero VAD: {e}") from e
def check_microphone(d):
 try:LOG.info("[SYSTEM] Mikrofon: %s",sd.query_devices(d,"input")["name"]);return True
 except Exception as e:LOG.error("[SYSTEM] Mikrofon tidak tersedia: %s",e);return False
def record_audio_with_vad(c:Config,vad:Any)->Path|None:
 q=queue.Queue(maxsize=64);pre=deque(maxlen=16);out=[];active=False;elapsed=silent=0.
 def cb(data,*args):
  try:q.put_nowait(data[:,0].copy())
  except queue.Full:
   try:q.get_nowait();q.put_nowait(data[:,0].copy())
   except queue.Empty:pass
 LOG.info("[BERU] Mendengarkan...")
 try:
  if hasattr(vad,"reset_states"):vad.reset_states()
  with sd.InputStream(samplerate=RATE,blocksize=BLOCK,channels=1,dtype="float32",device=c.device,callback=cb):
   while True:
    x=q.get(timeout=15)
    with torch.no_grad():speech=float(vad(torch.from_numpy(x),RATE).item())>=c.threshold
    if not active:
     pre.append(x)
     if speech:active=True;out.extend(pre);LOG.info("[VAD] Ucapan terdeteksi")
    else:
     out.append(x);elapsed+=BLOCK/RATE;silent=0 if speech else silent+BLOCK/RATE
     if elapsed>=c.minimum and silent>=c.silence:break
 except queue.Empty:LOG.info("[VAD] Tidak ada ucapan.");return None
 except Exception as e:LOG.error("[VAD] Gagal merekam: %s",e);return None
 if not out:return None
 p=create_temp_path("beru_input_",".wav");write(p,RATE,(np.clip(np.concatenate(out),-1,1)*32767).astype(np.int16));return p
def speech_to_text(p:Path,c:Config)->str:
 try:
  with p.open("rb") as f:
   with requests.post(GROQ,headers={"Authorization":f"Bearer {c.key}"},files={"file":(p.name,f,"audio/wav")},data={"model":"whisper-large-v3","language":"id","prompt":PROMPT},timeout=30) as r:
    r.raise_for_status();return str(r.json().get("text","")).strip()
 except (requests.RequestException,ValueError) as e:LOG.error("[STT] Groq gagal: %s",e);return ""
def normalize_stt(text:str)->str:
 t=re.sub(r"[^\w\s]"," ",text.lower());t=re.sub(r"\s+"," ",t).strip()
 ctx=r"(?=\s+(?:chrome|edge|firefox|vscode|visual|cmd|powershell|terminal|youtube|google|github|task|file|calculator|notepad)\b)"
 t=re.sub(r"\b(?:ukal|tuka|puka|bukak|bukain|buka\s+kan)\b"+ctx,"buka",t)
 for a,b in {r"\b(?:uaca|waca)\b":"cuaca",r"\b(?:chroom|krom|kro+om)\b":"chrome",r"\bvisual studio kode\b":"visual studio code",r"\btask meneger\b":"task manager",r"\bfile eksplorer\b":"file explorer"}.items():t=re.sub(a,b,t)
 return t
WAKE_PATTERN=re.compile(r"^(?:(?:halo|hai)\s+beru|beru)\b\s*",re.I)
WAKE_GREETING="Hai, saya BERU, asisten AI di laptopmu, Asbi. Mau ngapain hari ini?"
def detect_wake_phrase(text:str)->bool:
 """Deteksi token wake phrase di awal kalimat, tanpa false positive seperti 'berubah'."""
 return WAKE_PATTERN.match(text) is not None
def extract_command_after_wake_phrase(text:str)->str:
 """Kembalikan perintah sesudah wake phrase; string kosong berarti wake-only."""
 match=WAKE_PATTERN.match(text)
 return text[match.end():].strip() if match else text
def handle_wake_greeting(c:Config)->None:
 LOG.info("[BERU] %s",WAKE_GREETING)
 speak(WAKE_GREETING,c)
def get_current_datetime():
 n=datetime.now(ZoneInfo("Asia/Jakarta"));day=["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"][n.weekday()];mon=["Januari","Februari","Maret","April","Mei","Juni","Juli","Agustus","September","Oktober","November","Desember"][n.month-1]
 return {"datetime":f"{day}, {n.day} {mon} {n.year}, {n:%H:%M:%S} WIB","timezone":"Asia/Jakarta"}
def get_weather(c):
 try:
  r=requests.get("https://api.open-meteo.com/v1/forecast",params={"latitude":c.lat,"longitude":c.lon,"current":"temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code,precipitation","timezone":"Asia/Jakarta"},timeout=10);r.raise_for_status();x=r.json()["current"]
  names={0:"Cerah",1:"Sebagian besar cerah",2:"Berawan",3:"Mendung",45:"Berkabut",51:"Gerimis ringan",61:"Hujan ringan",63:"Hujan",65:"Hujan lebat",80:"Hujan lokal",95:"Badai petir"}
  return {"location":c.location,"temperature_c":x["temperature_2m"],"apparent_temperature_c":x["apparent_temperature"],"humidity_percent":x["relative_humidity_2m"],"wind_speed_kmh":x["wind_speed_10m"],"precipitation_mm":x["precipitation"],"condition":names.get(x.get("weather_code"),"Tidak diketahui")}
 except (requests.RequestException,KeyError,ValueError) as e:LOG.error("[TOOL] Cuaca: %s",e);return {"available":False,"message":"Informasi cuaca sedang tidak tersedia."}
def get_air_quality(c):
 try:
  r=requests.get("https://air-quality-api.open-meteo.com/v1/air-quality",params={"latitude":c.lat,"longitude":c.lon,"current":"us_aqi,pm2_5,pm10","timezone":"Asia/Jakarta"},timeout=10);r.raise_for_status();x=r.json()["current"];a=x["us_aqi"];label=next(v for k,v in [(50,"Baik"),(100,"Sedang"),(150,"Tidak sehat untuk kelompok sensitif"),(200,"Tidak sehat"),(300,"Sangat tidak sehat"),(9999,"Berbahaya")] if a<=k)
  return {"location":c.location,"aqi_us":a,"pm2_5_ug_m3":x["pm2_5"],"pm10_ug_m3":x["pm10"],"interpretation":label}
 except (requests.RequestException,KeyError,ValueError) as e:LOG.error("[TOOL] AQI: %s",e);return {"available":False,"message":"Informasi kualitas udara sedang tidak tersedia."}
def get_system_info():
 m=psutil.virtual_memory();d=psutil.disk_usage(os.getenv("SystemDrive","C:")+"\\");b=psutil.sensors_battery()
 return {"cpu_usage_percent":psutil.cpu_percent(.3),"ram_usage_percent":m.percent,"ram_available_gb":round(m.available/2**30,2),"disk_c_usage_percent":d.percent,"disk_c_free_gb":round(d.free/2**30,2),"battery_percent":None if not b else b.percent,"battery_charging":None if not b else b.power_plugged}
ALIASES={"visual studio code":"vscode","code":"vscode","google chrome":"chrome","terminal":"cmd","explorer":"file explorer","kalkulator":"calculator"}
PROCS={"vscode":"Code.exe","chrome":"chrome.exe","edge":"msedge.exe","firefox":"firefox.exe","photoshop":"Photoshop.exe","steam":"steam.exe","cmd":"cmd.exe","powershell":"powershell.exe","task manager":"Taskmgr.exe","file explorer":"explorer.exe","phone link":"PhoneExperienceHost.exe","calculator":"CalculatorApp.exe","notepad":"notepad.exe"}
def app(n):return ALIASES.get(n.lower().strip(),n.lower().strip())
FOLDERS={"download":"Downloads","downloads":"Downloads","unduhan":"Downloads","dokumen":"Documents","documents":"Documents","desktop":"Desktop","gambar":"Pictures","pictures":"Pictures","foto":"Pictures","videos":"Videos","video":"Videos","musik":"Music","music":"Music"}
REGISTRY_FOLDERS={"Downloads":"{374DE290-123F-4565-9164-39C4925E467B}","Documents":"Personal","Desktop":"Desktop","Pictures":"My Pictures","Videos":"My Video","Music":"My Music"}
def resolve_known_folder(folder_name:str)->tuple[str,Path|None]:
 """Cari Known Folder user tanpa menyisir seluruh drive; dukung redirection Windows."""
 key=folder_name.lower().strip().removeprefix("folder ").strip();canonical=FOLDERS.get(key)
 if not canonical:return folder_name,None
 candidates=[Path.home()/canonical]
 profile=os.getenv("USERPROFILE")
 if profile:candidates.append(Path(profile)/canonical)
 try:
  import winreg
  with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as reg:
   value,_=winreg.QueryValueEx(reg,REGISTRY_FOLDERS[canonical])
   candidates.insert(0,Path(os.path.expandvars(value)))
 except (ImportError,OSError):pass
 onedrive=os.getenv("OneDrive")
 if onedrive:candidates.append(Path(onedrive)/canonical)
 for candidate in candidates:
  if candidate.is_dir():return canonical,candidate
 return canonical,None
def open_folder(folder_name:str)->str:
 label,path=resolve_known_folder(folder_name)
 if path is None:return f"Folder {label} tidak ditemukan di lokasi pengguna Windows ini."
 try:os.startfile(str(path));return f"Folder {label} dibuka."
 except OSError as exc:LOG.error("[TOOL] Gagal membuka folder %s: %s",path,exc);return f"Gagal membuka folder {label}."
def open_app(app_name):
 if app_name.lower().strip().startswith("folder ") or app_name.lower().strip() in FOLDERS:return open_folder(app_name)
 a=app(app_name)
 if a in {"aplikasi","app","program",""}:return "Aplikasi mana yang ingin dibuka, Asbi?"
 if a not in PROCS:return "Aplikasi itu tidak ada dalam daftar aplikasi aman BERU."
 builtin={"cmd":"cmd.exe","powershell":"powershell.exe","task manager":"taskmgr.exe","file explorer":"explorer.exe","calculator":"calc.exe","notepad":"notepad.exe","phone link":"ms-phone:"}
 paths={"vscode":[Path(os.getenv("LOCALAPPDATA",""))/"Programs/Microsoft VS Code/Code.exe"],"chrome":[Path(os.getenv("PROGRAMFILES",""))/"Google/Chrome/Application/chrome.exe"],"steam":[Path(os.getenv("PROGRAMFILES(X86)",""))/"Steam/steam.exe"]}
 try:
  if a in builtin:os.startfile(builtin[a]);return f"{app_name} dibuka."
  p=shutil.which(PROCS[a]) or next((str(x) for x in paths.get(a,[]) if x.is_file()),None)
  if not p:return f"{app_name} tidak ditemukan di komputer ini."
  os.startfile(p);return f"{app_name} dibuka."
 except OSError:return f"Gagal membuka {app_name}."
def close_app(app_name):
 a=app(app_name)
 if a in {"aplikasi","app","program",""}:return "Aplikasi mana yang ingin ditutup, Asbi?"
 if a not in PROCS:return "Aplikasi itu tidak ada dalam daftar aplikasi aman BERU."
 process=PROCS[a].lower()
 def running():return any((proc.info.get("name") or "").lower()==process for proc in psutil.process_iter(["name"]))
 if not running():return f"{app_name} tidak sedang berjalan."
 try:
  result=subprocess.run(["taskkill","/F","/IM",PROCS[a]],capture_output=True,text=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
  if result.returncode!=0:return f"Windows tidak berhasil menutup {app_name}."
  for _ in range(15):
   if not running():return f"{app_name} berhasil ditutup."
   time.sleep(.2)
  return f"Windows menerima perintah, tetapi {app_name} masih berjalan sehingga belum dapat dipastikan tertutup."
 except (OSError,subprocess.TimeoutExpired) as exc:LOG.error("[TOOL] Gagal menutup %s: %s",app_name,exc);return f"Gagal menutup {app_name}."
def open_website(url_or_site):
 t=url_or_site.strip();l=t.lower();sites={"google":"https://www.google.com","youtube":"https://www.youtube.com","github":"https://github.com","chatgpt":"https://chatgpt.com"}
 if l in sites:t=sites[l]
 elif re.match(r"^cari\s+.+\s+di\s+youtube$",l):t="https://www.youtube.com/results?search_query="+quote_plus(re.sub(r"^cari\s+(.+)\s+di\s+youtube$",r"\1",t,flags=re.I))
 elif not urlparse(t).scheme:t="https://"+(t if "." in t else t+".com")
 if urlparse(t).scheme not in {"http","https"} or not urlparse(t).netloc:return "Alamat website tidak valid."
 webbrowser.open(t,new=2);return "Website dibuka."
SAFE={"ping","ipconfig","whoami","python","php","git","npm","composer"};DANGER={"shutdown","restart","format","diskpart","del","erase","rmdir","rd","reg"};PENDING=None
def run_terminal_command(command):
 global PENDING
 args=command.strip().split()
 if not args:return "Perintah terminal kosong."
 program=args[0].lower().removesuffix(".exe")
 if program in DANGER:PENDING=args;return "CONFIRMATION_REQUIRED: Asbi, kamu yakin ingin menjalankan perintah berbahaya itu?"
 if program not in SAFE or any(x in command for x in ("&","|",";",">","<",chr(96))):return "Perintah itu tidak diizinkan demi keamanan."
 try:r=subprocess.run(args,capture_output=True,text=True,timeout=20,shell=False,creationflags=subprocess.CREATE_NO_WINDOW);return json.dumps({"returncode":r.returncode,"output":(r.stdout or r.stderr).strip()[:3000]},ensure_ascii=False)
 except subprocess.TimeoutExpired:return "Perintah terminal melebihi batas waktu dan dihentikan."
 except OSError:return "Perintah terminal gagal dijalankan."
def confirm_dangerous_command(text):
 global PENDING
 if not PENDING:return None
 if text.lower().strip() not in {"ya","iya","yakin","konfirmasi","lanjut","jalankan"}:PENDING=None;return "Baik, perintah berbahaya dibatalkan."
 x=PENDING[0].lower();PENDING=None
 if x in {"shutdown","restart"}:subprocess.Popen(["shutdown","/r" if x=="restart" else "/s","/t","0"],creationflags=subprocess.CREATE_NO_WINDOW);return "Perintah sistem dijalankan."
 return "Demi keamanan, perintah itu tidak didukung untuk eksekusi otomatis."
def schema(n,d,p={},r=[]):return {"type":"function","function":{"name":n,"description":d,"parameters":{"type":"object","properties":p,"required":r}}}
OLLAMA_TOOLS=[schema("get_current_datetime","Waktu realtime Asia/Jakarta."),schema("get_weather","Cuaca realtime."),schema("get_air_quality","Kualitas udara."),schema("get_system_info","CPU RAM disk dan baterai."),schema("open_app","Buka aplikasi Windows.",{"app_name":{"type":"string"}},["app_name"]),schema("open_folder","Buka folder Windows umum seperti Downloads, Documents, Desktop, Pictures, Videos, atau Music.",{"folder_name":{"type":"string"}},["folder_name"]),schema("close_app","Tutup aplikasi Windows bernama spesifik, lalu verifikasi prosesnya.",{"app_name":{"type":"string"}},["app_name"]),schema("open_website","Buka website.",{"url_or_site":{"type":"string"}},["url_or_site"]),schema("run_terminal_command","Command aman.",{"command":{"type":"string"}},["command"])]
def execute_tool(n,args,c):
 LOG.info("[TOOL] %s",n);f={"get_current_datetime":get_current_datetime,"get_weather":lambda:get_weather(c),"get_air_quality":lambda:get_air_quality(c),"get_system_info":get_system_info,"open_app":open_app,"open_folder":open_folder,"close_app":close_app,"open_website":open_website,"run_terminal_command":run_terminal_command}.get(n)
 try:return f(**args) if f else {"error":"Tool tidak dikenali."}
 except Exception as e:LOG.error("[TOOL] gagal: %s",e);return {"error":"Tool gagal."}
SYSTEM="Kamu adalah BERU, asisten pribadi Asbi. Selalu Bahasa Indonesia, ramah dan ringkas 1-2 kalimat. Input STT dapat typo; pahami konteks. Gunakan tool untuk data realtime dan aksi komputer. Untuk folder Downloads, Documents, Desktop, Pictures, Videos, atau Music gunakan open_folder. Untuk 'tutup aplikasi' tanpa nama, minta nama aplikasi dan jangan mengklaim aksi berhasil. Respons final harus sesuai hasil tool; jangan mengarang hasil tool atau berkata Sebagai AI."
def ollama_chat(user,history,c):
 messages=[{"role":"system","content":SYSTEM},*history,{"role":"user","content":user}]
 try:
  r=requests.post(c.chat,json={"model":c.model,"messages":messages,"tools":OLLAMA_TOOLS,"stream":False},timeout=45);r.raise_for_status();a=r.json().get("message",{});messages.append(a)
  for call in a.get("tool_calls",[]):f=call.get("function",{});messages.append({"role":"tool","content":json.dumps(execute_tool(f.get("name",""),f.get("arguments",{}),c),ensure_ascii=False)})
  if a.get("tool_calls"):r=requests.post(c.chat,json={"model":c.model,"messages":messages,"stream":False},timeout=45);r.raise_for_status();answer=str(r.json().get("message",{}).get("content","")).strip()
  else:answer=str(a.get("content","")).strip()
  history.extend(({"role":"user","content":user},{"role":"assistant","content":answer}));return answer or "Siap, Asbi."
 except (requests.RequestException,ValueError) as e:LOG.error("[LLM] Ollama gagal: %s",e);return "Maaf Asbi, Ollama sedang tidak bisa dihubungi."
async def text_to_speech(text,path,c):await edge_tts.Communicate(text,c.voice,rate=c.tts_rate,volume=c.tts_volume,pitch=c.tts_pitch).save(str(path))
def play_audio(path):
 v=create_temp_path("beru_play_",".vbs");s=str(path.resolve()).replace('"','""')
 try:
  v.write_text(f'Set p=CreateObject("WMPlayer.OCX")\np.URL="{s}"\np.controls.play\nstarted=False\nFor i=1 To 600\n WScript.Sleep 100\n If p.playState=3 Then started=True\n If started And p.playState=1 Then Exit For\nNext\np.close\n',encoding="utf-8")
  return subprocess.run(["cscript.exe","//nologo",str(v)],timeout=70,creationflags=subprocess.CREATE_NO_WINDOW).returncode==0
 except (OSError,subprocess.TimeoutExpired) as e:LOG.error("[TTS] Pemutar gagal: %s",e);return False
 finally:cleanup_temp_file(v)
def speak(text,c):
 p=create_temp_path("beru_response_",".mp3")
 try:asyncio.run(text_to_speech(text,p,c));play_audio(p)
 except Exception as e:LOG.error("[TTS] Edge TTS gagal: %s",e)
 finally:cleanup_temp_file(p)
def main():
 setup_logging();print("========================================\n        BERU AI AGENT\n        Personal Assistant\n========================================")
 try:c=load_config()
 except RuntimeError as e:LOG.error("[SYSTEM] %s",e);return
 print("✓ Configuration");print(("✓" if check_ollama(c) else "!")+" Ollama")
 if not check_microphone(c.device):return
 print("✓ Microphone")
 try:vad=initialize_vad()
 except RuntimeError as e:LOG.error("[SYSTEM] %s",e);return
 print("✓ VAD\n✓ TTS\n\nBERU siap digunakan.");history=deque(maxlen=12)
 while True:
  audio=record_audio_with_vad(c,vad)
  if not audio:continue
  try:raw=speech_to_text(audio,c)
  finally:cleanup_temp_file(audio)
  if not raw:continue
  text=normalize_stt(raw);LOG.info("[STT] %s",text)
  if detect_wake_phrase(text):
   text=extract_command_after_wake_phrase(text)
   if not text:handle_wake_greeting(c);continue
  if text in {"keluar","exit","berhenti","stop beru","beru keluar","beru exit","beru shutdown","beru berhenti"}:speak("Siap, Asbi. Sampai nanti.",c);break
  answer=confirm_dangerous_command(text)
  if answer is None:LOG.info("[BERU] Memproses...");answer=ollama_chat(text,history,c)
  LOG.info("[BERU] %s",answer);speak(answer,c);time.sleep(.15)
if __name__=="__main__":main()
