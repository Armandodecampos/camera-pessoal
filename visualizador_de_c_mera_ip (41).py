import cv2
import numpy as np
import datetime
import os
import json
import threading
import time
import socket
import tkinter as tk
from tkinter import simpledialog

# Arquivo de configuração local
CONFIG_FILE = "config.json"

# Configurações padrão
DEFAULT_CONFIG = {
    "camera_ip": "192.168.0.10",
    "flip_h": False,
    "flip_v": False,
    "rotation_angle": 0
}

def load_config():
    """Carrega as configurações salvas no arquivo JSON"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                print("[CONFIG] Configurações carregadas com sucesso!")
                return {**DEFAULT_CONFIG, **config}
        except Exception as e:
            print(f"[CONFIG] Erro ao carregar configurações: {e}")
    return DEFAULT_CONFIG.copy()

def save_config():
    """Salva as configurações atuais no arquivo JSON"""
    config_data = {
        "camera_ip": camera_ip,
        "flip_h": flip_h,
        "flip_v": flip_v,
        "rotation_angle": rotation_angle
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
        print("[CONFIG] Configurações salvas.")
    except Exception as e:
        print(f"[CONFIG] Erro ao salvar configurações: {e}")

# Estado das Configurações
config = load_config()
camera_ip = config.get("camera_ip", "192.168.0.10")
flip_h = config.get("flip_h", False)
flip_v = config.get("flip_v", False)
rotation_angle = config.get("rotation_angle", 0)

# Variáveis Globais de Controle da Aplicação
cap = None
is_connected = False
is_connecting = False
stop_threads = False
reconnect_event = threading.Event()
current_connection_id = 0

def change_camera_ip(new_ip):
    """Atualiza o IP da câmera, cancela conexões ativas/em andamento e reinicia o loop de conexão imediatamente"""
    global camera_ip, cap, is_connected, is_connecting, current_connection_id
    if not new_ip:
        return
    new_ip = new_ip.strip()
    if not new_ip:
        return

    print(f"[CONEXÃO] Alterando IP da câmera para: {new_ip} (Interrompendo tentativas anteriores)")
    camera_ip = new_ip
    current_connection_id += 1
    save_config()

    if cap is not None:
        try:
            cap.release()
        except Exception as e:
            print(f"[AVISO] Erro ao liberar cap anterior: {e}")
        cap = None

    is_connected = False
    is_connecting = False
    # Notifica a thread de conexão para interromper esperas e tentar o novo IP imediatamente
    reconnect_event.set()

menu_open = False
sub_menu = None  # None, 'config', 'scanner'

is_recording = False
video_writer = None
patrol_active = False

motion_detection = False
prev_gray_frame = None

discovered_devices = []
is_scanning = False

# Criar diretórios para salvar arquivos
save_dir_videos = os.path.join(os.path.expanduser('~'), 'Documents', 'CameraCaptures')
save_dir_prints = os.path.join(save_dir_videos, 'Prints')
os.makedirs(save_dir_videos, exist_ok=True)
os.makedirs(save_dir_prints, exist_ok=True)

print(f"[PASTAS DE SALVAMENTO]:\n - Vídeos: {save_dir_videos}\n - Prints: {save_dir_prints}")

def connect_camera_thread():
    """Thread em segundo plano para conectar e gerenciar o streaming da câmera de forma contínua e interrompível"""
    global cap, is_connected, is_connecting, stop_threads, camera_ip, current_connection_id, reconnect_event

    while not stop_threads:
        if cap is None or not cap.isOpened():
            is_connected = False
            is_connecting = True

            # Captura os dados da tentativa atual
            target_ip = camera_ip
            attempt_id = current_connection_id
            reconnect_event.clear()

            urls = [
                f"http://{target_ip}:81/stream",
                f"http://{target_ip}/stream",
                f"http://{target_ip}:8080/video"
            ]

            connected_this_round = False
            for url in urls:
                # Interrompe se o usuário solicitou parada ou mudou de IP
                if stop_threads or reconnect_event.is_set() or attempt_id != current_connection_id:
                    break

                print(f"[RECONEXÃO] Tentando conectar em {url}...")
                temp_cap = cv2.VideoCapture(url)

                start_t = time.time()
                while time.time() - start_t < 2.0:
                    if stop_threads or reconnect_event.is_set() or attempt_id != current_connection_id:
                        temp_cap.release()
                        temp_cap = None
                        break

                    if temp_cap.isOpened():
                        # Verifica se o IP ainda é o mesmo antes de associar
                        if attempt_id == current_connection_id and not reconnect_event.is_set() and not stop_threads:
                            cap = temp_cap
                            is_connected = True
                            is_connecting = False
                            connected_this_round = True
                            print(f"[RECONEXÃO] Câmera conectada com sucesso em {url}!")
                        else:
                            temp_cap.release()
                        break
                    time.sleep(0.1)

                if connected_this_round:
                    break
                elif temp_cap is not None:
                    temp_cap.release()

            # Se o IP mudou enquanto tentava, reinicia o loop imediatamente para o novo IP
            if attempt_id != current_connection_id or reconnect_event.is_set():
                is_connecting = False
                continue

            if not is_connected:
                is_connecting = True
                # Espera curta (1.5s) antes da próxima tentativa em loop, mas interrompe imediatamente se houver novo IP
                reconnect_event.wait(timeout=1.5)
            else:
                is_connecting = False
        else:
            # Já conectado; aguarda evento de reconexão ou verifica periodicamente se o stream caiu
            reconnect_event.wait(timeout=1.0)

def scan_single_ip(ip, results):
    """Verifica se um IP específico possui a porta HTTP (80/81/8080) aberta"""
    for port in [80, 81, 8080]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.15)
            res = sock.connect_ex((ip, port))
            if res == 0:
                try:
                    hostname = socket.gethostbyaddr(ip)[0]
                except socket.error:
                    hostname = "Dispositivo de Rede"
                results.append((ip, hostname))
                sock.close()
                break
            sock.close()
        except:
            pass

def start_network_scan():
    """Inicia o escaneamento de rede em segundo plano"""
    global is_scanning, discovered_devices
    if is_scanning:
        return

    is_scanning = True
    discovered_devices = []

    def run_scan():
        global is_scanning, discovered_devices
        results = []
        threads = []
        base_ip = "192.168.0."
        print("[SCANNER] Iniciando varredura da rede...")
        
        for i in range(1, 255):
            target_ip = f"{base_ip}{i}"
            t = threading.Thread(target=scan_single_ip, args=(target_ip, results))
            t.daemon = True
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        discovered_devices = sorted(results, key=lambda x: [int(pt) for pt in x[0].split('.')])
        is_scanning = False
        print(f"[SCANNER] Varredura concluída. Encontrados {len(discovered_devices)} dispositivos.")

    thread = threading.Thread(target=run_scan)
    thread.daemon = True
    thread.start()

def prompt_new_ip():
    """Abre uma janela simples do Tkinter para o usuário digitar um novo IP"""
    global camera_ip
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        
        new_ip = simpledialog.askstring("Mudar IP da Camera", "Digite o novo Endereco IP:", initialvalue=camera_ip, parent=root)
        root.destroy()
        
        if new_ip and new_ip.strip() != "":
            change_camera_ip(new_ip)
    except Exception as e:
        print(f"[ERRO] Erro na janela de IP: {e}")

def letterbox_frame(frame, target_w, target_h):
    """Ajusta a imagem para caber no tamanho alvo mantendo a proporção exata (sem distorção) com letterbox."""
    fh, fw = frame.shape[:2]
    if fw <= 0 or fh <= 0:
        return np.zeros((target_h, target_w, 3), dtype=np.uint8)

    scale = min(target_w / fw, target_h / fh)
    nw, nh = max(1, int(round(fw * scale))), max(1, int(round(fh * scale)))

    if fw == nw and fh == nh:
        resized = frame
    else:
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)

    canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    ox = (target_w - nw) // 2
    oy = (target_h - nh) // 2
    canvas[oy:oy+nh, ox:ox+nw] = resized
    return canvas

def update_window_size(window_name, width, height):
    """Ajusta o tamanho da janela OpenCV dependendo da orientação (retrato ou paisagem)"""
    try:
        cv2.resizeWindow(window_name, width, height)
    except Exception as e:
        print(f"[ERRO] Falha ao redimensionar janela: {e}")

def draw_rounded_rect(img, pt1, pt2, color, radius=6, thickness=-1):
    """Desenha um retângulo com cantos arredondados suavemente."""
    x1, y1 = pt1
    x2, y2 = pt2
    r = max(1, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
    if thickness == -1:
        cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), color, -1)
        cv2.rectangle(img, (x1, y1 + r), (x2, y2 - r), color, -1)
        cv2.circle(img, (x1 + r, y1 + r), r, color, -1)
        cv2.circle(img, (x2 - r, y1 + r), r, color, -1)
        cv2.circle(img, (x1 + r, y2 - r), r, color, -1)
        cv2.circle(img, (x2 - r, y2 - r), r, color, -1)
    else:
        cv2.line(img, (x1 + r, y1), (x2 - r, y1), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x1 + r, y2), (x2 - r, y2), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x1, y1 + r), (x1, y2 - r), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x2, y1 + r), (x2, y2 - r), color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x1 + r, y1 + r), (r, r), 180, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x2 - r, y1 + r), (r, r), 270, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x2 - r, y2 - r), (r, r), 0, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x1 + r, y2 - r), (r, r), 90, 0, 90, color, thickness, cv2.LINE_AA)

def draw_menu_panel(img, pt1, pt2, title):
    """Desenha o container do menu com fundo translúcido escuro e título centralizado."""
    x1, y1 = pt1
    x2, y2 = pt2
    sub = img[y1:y2, x1:x2]
    if sub.size > 0:
        bg = np.full_like(sub, (22, 25, 32), dtype=np.uint8)
        cv2.addWeighted(bg, 0.94, sub, 0.06, 0, sub)
        img[y1:y2, x1:x2] = sub
    draw_rounded_rect(img, pt1, pt2, (60, 68, 85), radius=8, thickness=1)

    (tw, th), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
    tx = x1 + ((x2 - x1) - tw) // 2
    cv2.putText(img, title, (tx, y1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (235, 240, 250), 1, cv2.LINE_AA)
    cv2.line(img, (x1 + 14, y1 + 32), (x2 - 14, y1 + 32), (50, 58, 72), 1, cv2.LINE_AA)

def draw_menu_button(img, pt1, pt2, text, bg_color, text_color=(240, 245, 250), border_color=(65, 75, 95), font_scale=0.35, center=True):
    """Desenha um botão estilizado com cantos suaves e texto alinhado."""
    x1, y1 = pt1
    x2, y2 = pt2
    draw_rounded_rect(img, pt1, pt2, bg_color, radius=6, thickness=-1)
    if border_color:
        draw_rounded_rect(img, pt1, pt2, border_color, radius=6, thickness=1)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
    btn_w = x2 - x1
    btn_h = y2 - y1
    ty = y1 + (btn_h + th) // 2
    tx = x1 + (btn_w - tw) // 2 if center else x1 + 14
    cv2.putText(img, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_color, 1, cv2.LINE_AA)

def mouse_callback(event, x, y, flags, param):
    """Gerenciador de cliques de mouse nos botões da interface"""
    global menu_open, sub_menu, is_recording, video_writer, motion_detection
    global flip_h, flip_v, rotation_angle, prev_gray_frame, camera_ip, cap

    if event == cv2.EVENT_LBUTTONDOWN:
        # Clique no Botao de Menu (Icone Hamburguer / Fechar: X: 12 a 46, Y: 12 a 44)
        if 12 <= x <= 46 and 12 <= y <= 44:
            menu_open = not menu_open
            sub_menu = None
            return

        if menu_open:
            btn_x1, btn_x2 = 24, 188
            if sub_menu is None:
                # Opcao 1: Tirar Foto (Y: 96 a 124)
                if btn_x1 <= x <= btn_x2 and 96 <= y <= 124:
                    param['take_photo'] = True

                # Opcao 2: Gravar Video (Y: 132 a 160)
                elif btn_x1 <= x <= btn_x2 and 132 <= y <= 160:
                    is_recording = not is_recording

                # Opcao 3: Deteccao Movimento (Y: 168 a 196)
                elif btn_x1 <= x <= btn_x2 and 168 <= y <= 196:
                    motion_detection = not motion_detection
                    prev_gray_frame = None

                # Opcao 4: Configuracoes (Y: 204 a 232)
                elif btn_x1 <= x <= btn_x2 and 204 <= y <= 232:
                    sub_menu = 'config'

            elif sub_menu == 'config':
                # Botao Voltar (Y: 96 a 122)
                if btn_x1 <= x <= btn_x2 and 96 <= y <= 122:
                    sub_menu = None

                # Botao Inverter Horizontal (Y: 130 a 156)
                elif btn_x1 <= x <= btn_x2 and 130 <= y <= 156:
                    flip_h = not flip_h
                    save_config()

                # Botao Inverter Vertical (Y: 164 a 190)
                elif btn_x1 <= x <= btn_x2 and 164 <= y <= 190:
                    flip_v = not flip_v
                    save_config()

                # Botoes de Rotacao (Y: 198 a 224)
                # 0 deg: 24..61 | 90 deg: 66..103 | 180 deg: 108..145 | 270 deg: 150..187
                elif 198 <= y <= 224:
                    if 24 <= x <= 61:
                        rotation_angle = 0
                        prev_gray_frame = None
                        save_config()
                        param['need_resize'] = True
                    elif 66 <= x <= 103:
                        rotation_angle = 90
                        prev_gray_frame = None
                        save_config()
                        param['need_resize'] = True
                    elif 108 <= x <= 145:
                        rotation_angle = 180
                        prev_gray_frame = None
                        save_config()
                        param['need_resize'] = True
                    elif 150 <= x <= 187:
                        rotation_angle = 270
                        prev_gray_frame = None
                        save_config()
                        param['need_resize'] = True

                # Botao Rede e IP (Y: 232 a 258)
                elif btn_x1 <= x <= btn_x2 and 232 <= y <= 258:
                    sub_menu = 'scanner'
                    start_network_scan()

            elif sub_menu == 'scanner':
                # Botao Voltar (Y: 96 a 122) -> Volta para Configuracoes
                if btn_x1 <= x <= btn_x2 and 96 <= y <= 122:
                    sub_menu = 'config'

                # Botao Mudar IP Manualmente (Y: 130 a 156)
                elif btn_x1 <= x <= btn_x2 and 130 <= y <= 156:
                    prompt_new_ip()

                # Botao Escanear Novamente (Y: 164 a 190)
                elif btn_x1 <= x <= btn_x2 and 164 <= y <= 190:
                    if not is_scanning:
                        start_network_scan()

                # Selecao de IP da lista clicavel (Y inicia em 228, altura 24, gap 4)
                else:
                    max_show = min(5, len(discovered_devices))
                    for idx in range(max_show):
                        item_y_start = 228 + (idx * 28)
                        item_y_end = item_y_start + 24
                        if btn_x1 <= x <= btn_x2 and item_y_start <= y <= item_y_end:
                            selected_ip, _ = discovered_devices[idx]
                            if camera_ip != selected_ip:
                                change_camera_ip(selected_ip)
                            break

def main():
    global stop_threads, video_writer, cap, prev_gray_frame, is_recording

    window_name = "Visualizador de Camera IP"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

    w_init, h_init = (450, 600) if rotation_angle in [90, 270] else (960, 540)
    update_window_size(window_name, w_init, h_init)

    mouse_params = {'take_photo': False, 'need_resize': False}
    cv2.setMouseCallback(window_name, mouse_callback, mouse_params)

    # Inicia a thread de conexao em segundo plano
    conn_thread = threading.Thread(target=connect_camera_thread)
    conn_thread.daemon = True
    conn_thread.start()

    last_record_state = False

    while True:
        # Se houve mudanca na rotacao, redimensiona a janela
        if mouse_params['need_resize']:
            w, h = (450, 600) if rotation_angle in [90, 270] else (960, 540)
            update_window_size(window_name, w, h)
            mouse_params['need_resize'] = False

        frame = None
        if cap is not None and cap.isOpened():
            try:
                ret, raw_frame = cap.read()
                if ret and raw_frame is not None:
                    frame = raw_frame
            except Exception as e:
                frame = None

        # Se nao ha frame da camera, gera tela estatica de espera
        if frame is None:
            canvas_w, canvas_h = (450, 600) if rotation_angle in [90, 270] else (960, 540)
            display_frame = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
            
            txt = "Buscando Sinal da Camera..." if is_connecting else f"Camera Offline ({camera_ip})"
            cv2.putText(display_frame, txt, (20, canvas_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
            cv2.putText(display_frame, "Menu: Mudar IP ou Buscar na Rede", (20, (canvas_h // 2) + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1)
        else:
            # Aplica rotacao na imagem
            if rotation_angle == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif rotation_angle == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif rotation_angle == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

            # Aplica Inversoes (Horizontal / Vertical)
            if flip_h and flip_v:
                frame = cv2.flip(frame, -1)
            elif flip_h:
                frame = cv2.flip(frame, 1)
            elif flip_v:
                frame = cv2.flip(frame, 0)

            # Ajusta o frame para bater com a dimensao da janela mantendo a proporcao (sem distorcer)
            canvas_w, canvas_h = (450, 600) if rotation_angle in [90, 270] else (960, 540)
            display_frame = letterbox_frame(frame, canvas_w, canvas_h)

            # Deteccao de Movimento
            if motion_detection:
                gray = cv2.cvtColor(display_frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                if prev_gray_frame is not None and prev_gray_frame.shape == gray.shape:
                    frame_delta = cv2.absdiff(prev_gray_frame, gray)
                    thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                    thresh = cv2.dilate(thresh, None, iterations=2)
                    contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                    for c in contours:
                        if cv2.contourArea(c) < 1500:
                            continue
                        (x_m, y_m, w_m, h_m) = cv2.boundingRect(c)
                        cv2.rectangle(display_frame, (x_m, y_m), (x_m + w_m, y_m + h_m), (0, 0, 255), 2)
                        cv2.putText(display_frame, "MOVIMENTO DETECTADO", (10, display_frame.shape[0] - 20),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)

                prev_gray_frame = gray

        # Captura de Foto
        if mouse_params['take_photo']:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(save_dir_prints, f"Foto_{timestamp}.jpg")
            cv2.imwrite(filename, display_frame)
            print(f"[FOTO] Salva com sucesso em: {filename}")
            mouse_params['take_photo'] = False

        # Gravacao de Video
        if is_recording:
            if not last_record_state:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(save_dir_videos, f"Video_{timestamp}.avi")
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
                h_rec, w_rec = display_frame.shape[:2]
                video_writer = cv2.VideoWriter(filename, fourcc, 20.0, (w_rec, h_rec))
                print(f"[GRAVACAO] Iniciada: {filename}")
                last_record_state = True

            if video_writer is not None:
                video_writer.write(display_frame)
                cv2.circle(display_frame, (display_frame.shape[1] - 25, 25), 8, (0, 0, 255), -1)
                cv2.putText(display_frame, "REC", (display_frame.shape[1] - 65, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
        else:
            if last_record_state:
                if video_writer is not None:
                    video_writer.release()
                    video_writer = None
                print("[GRAVACAO] Finalizada.")
                last_record_state = False

        # Botao Principal de Menu (Design Moderno com cantos arredondados)
        btn_hb_bg = (48, 55, 72) if menu_open else (28, 32, 42)
        btn_hb_border = (90, 105, 135) if menu_open else (60, 68, 85)
        draw_rounded_rect(display_frame, (12, 12), (46, 44), btn_hb_bg, radius=6, thickness=-1)
        draw_rounded_rect(display_frame, (12, 12), (46, 44), btn_hb_border, radius=6, thickness=1)

        cx, cy = 29, 28
        if menu_open:
            cv2.line(display_frame, (cx - 7, cy - 7), (cx + 7, cy + 7), (255, 255, 255), 2, cv2.LINE_AA)
            cv2.line(display_frame, (cx - 7, cy + 7), (cx + 7, cy - 7), (255, 255, 255), 2, cv2.LINE_AA)
        else:
            cv2.line(display_frame, (cx - 8, cy - 6), (cx + 8, cy - 6), (240, 245, 250), 2, cv2.LINE_AA)
            cv2.line(display_frame, (cx - 8, cy),     (cx + 8, cy),     (240, 245, 250), 2, cv2.LINE_AA)
            cv2.line(display_frame, (cx - 8, cy + 6), (cx + 8, cy + 6), (240, 245, 250), 2, cv2.LINE_AA)

        # Desenho da Interface de Menus Moderna e Alinhada
        if menu_open:
            bx1, bx2 = 24, 188

            if sub_menu is None:
                # Painel Principal
                draw_menu_panel(display_frame, (12, 54), (200, 246), "MENU PRINCIPAL")

                draw_menu_button(display_frame, (bx1, 96), (bx2, 124), "Tirar Foto", (36, 42, 55), border_color=(65, 75, 95))

                rec_bg = (120, 35, 45) if is_recording else (36, 42, 55)
                rec_border = (200, 60, 75) if is_recording else (65, 75, 95)
                draw_menu_button(display_frame, (bx1, 132), (bx2, 160), "Parar Gravacao" if is_recording else "Gravar Video", rec_bg, border_color=rec_border)

                mot_bg = (30, 110, 50) if motion_detection else (36, 42, 55)
                mot_border = (50, 180, 85) if motion_detection else (65, 75, 95)
                draw_menu_button(display_frame, (bx1, 168), (bx2, 196), "Det. Movimento", mot_bg, border_color=mot_border)

                draw_menu_button(display_frame, (bx1, 204), (bx2, 232), "Configuracoes >", (45, 52, 68), border_color=(80, 95, 120))

            elif sub_menu == 'config':
                # Painel de Configuracoes
                draw_menu_panel(display_frame, (12, 54), (200, 272), "CONFIGURACOES")

                draw_menu_button(display_frame, (bx1, 96), (bx2, 122), "< Voltar", (30, 35, 46), text_color=(180, 190, 205), border_color=(55, 65, 80))

                h_bg = (30, 110, 50) if flip_h else (36, 42, 55)
                h_border = (50, 180, 85) if flip_h else (65, 75, 95)
                draw_menu_button(display_frame, (bx1, 130), (bx2, 156), f"Inverter Horiz: {'LIG' if flip_h else 'DES'}", h_bg, border_color=h_border)

                v_bg = (30, 110, 50) if flip_v else (36, 42, 55)
                v_border = (50, 180, 85) if flip_v else (65, 75, 95)
                draw_menu_button(display_frame, (bx1, 164), (bx2, 190), f"Inverter Vert: {'LIG' if flip_v else 'DES'}", v_bg, border_color=v_border)

                # Botoes de Rotacao em grid alinhado
                angles = [0, 90, 180, 270]
                ang_x = [24, 66, 108, 150]
                for idx_ang, ang in enumerate(angles):
                    x_s = ang_x[idx_ang]
                    is_cur = (rotation_angle == ang)
                    bg_ang = (30, 110, 50) if is_cur else (36, 42, 55)
                    brd_ang = (50, 180, 85) if is_cur else (65, 75, 95)
                    draw_menu_button(display_frame, (x_s, 198), (x_s + 37, 224), f"{ang}", bg_ang, border_color=brd_ang, font_scale=0.32)

                draw_menu_button(display_frame, (bx1, 232), (bx2, 258), "Rede e IP >", (45, 52, 68), border_color=(80, 95, 120))

            elif sub_menu == 'scanner':
                # Painel do Scanner de Rede
                max_show = min(5, len(discovered_devices))
                scanner_panel_h = 236 + (max_show * 28) if max_show > 0 else 240
                draw_menu_panel(display_frame, (12, 54), (200, scanner_panel_h), "REDE E IP")

                draw_menu_button(display_frame, (bx1, 96), (bx2, 122), "< Voltar", (30, 35, 46), text_color=(180, 190, 205), border_color=(55, 65, 80))
                draw_menu_button(display_frame, (bx1, 130), (bx2, 156), "Mudar IP", (55, 42, 90), border_color=(95, 75, 150))

                scan_bg = (30, 35, 45) if is_scanning else (30, 110, 50)
                scan_border = (55, 65, 80) if is_scanning else (50, 180, 85)
                draw_menu_button(display_frame, (bx1, 164), (bx2, 190), "Buscando..." if is_scanning else "Escanear Rede", scan_bg, border_color=scan_border)

                # Subtitulo da lista de IPs
                (tw_c, _), _ = cv2.getTextSize(f"IPs Encontrados ({len(discovered_devices)})", cv2.FONT_HERSHEY_SIMPLEX, 0.30, 1)
                tx_c = 12 + (188 - tw_c) // 2
                cv2.putText(display_frame, f"IPs Encontrados ({len(discovered_devices)})", (tx_c, 212), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (180, 195, 215), 1, cv2.LINE_AA)

                for idx in range(max_show):
                    ip_addr, _ = discovered_devices[idx]
                    is_active_ip = (ip_addr == camera_ip)
                    item_y_start = 228 + (idx * 28)
                    item_y_end = item_y_start + 24
                    ip_bg = (30, 75, 40) if is_active_ip else (28, 33, 44)
                    ip_border = (50, 160, 80) if is_active_ip else (50, 60, 75)
                    ip_text_col = (180, 255, 200) if is_active_ip else (220, 225, 235)
                    label = f"* {ip_addr}" if is_active_ip else ip_addr
                    draw_menu_button(display_frame, (bx1, item_y_start), (bx2, item_y_end), label, ip_bg, text_color=ip_text_col, border_color=ip_border, font_scale=0.32)

        cv2.imshow(window_name, display_frame)

        key = cv2.waitKey(30) & 0xFF
        if key == ord('q') or key == 27:
            print("[ENCERRANDO] Aplicacao fechada pelo usuario.")
            stop_threads = True
            save_config()
            break

    if video_writer is not None:
        video_writer.release()
    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()