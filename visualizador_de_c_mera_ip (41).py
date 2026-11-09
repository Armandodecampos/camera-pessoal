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
    "rotation_angle": 0,
    "exposure_manual": False,
    "exposure_val": 0
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
        "rotation_angle": rotation_angle,
        "exposure_manual": exposure_manual,
        "exposure_val": exposure_val
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
exposure_manual = config.get("exposure_manual", False)
exposure_val = config.get("exposure_val", 0)

# Variáveis Globais de Controle da Aplicação
cap = None
is_connected = False
is_connecting = False
stop_threads = False

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
    """Thread em segundo plano para conectar e gerenciar o streaming da câmera de forma não bloqueante"""
    global cap, is_connected, is_connecting, stop_threads, camera_ip

    while not stop_threads:
        if cap is None or not cap.isOpened():
            is_connected = False
            is_connecting = True
            
            # Formatos de URL de câmeras IP comuns
            urls = [
                f"http://{camera_ip}:81/stream",
                f"http://{camera_ip}/stream",
                f"http://{camera_ip}:8080/video"
            ]
            
            for url in urls:
                if stop_threads:
                    break
                print(f"[RECONEXÃO] Tentando conectar em {url}...")
                temp_cap = cv2.VideoCapture(url)
                
                # Aguarda abertura com limite de tempo
                start_t = time.time()
                while time.time() - start_t < 2.5:
                    if temp_cap.isOpened():
                        cap = temp_cap
                        is_connected = True
                        is_connecting = False
                        print("[RECONEXÃO] Câmera conectada com sucesso!")
                        break
                    time.sleep(0.1)

                if is_connected:
                    break
                else:
                    temp_cap.release()

            is_connecting = False

        time.sleep(3.0)

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
    global camera_ip, cap
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        
        new_ip = simpledialog.askstring("Mudar IP da Camera", "Digite o novo Endereco IP:", initialvalue=camera_ip, parent=root)
        root.destroy()
        
        if new_ip and new_ip.strip() != "":
            camera_ip = new_ip.strip()
            save_config()
            print(f"[CONFIG] IP atualizado para: {camera_ip}")
            if cap is not None:
                cap.release()
                cap = None
    except Exception as e:
        print(f"[ERRO] Erro na janela de IP: {e}")

def update_window_size(window_name, width, height):
    """Ajusta o tamanho da janela OpenCV dependendo da orientação (retrato ou paisagem)"""
    try:
        cv2.resizeWindow(window_name, width, height)
    except Exception as e:
        print(f"[ERRO] Falha ao redimensionar janela: {e}")

def mouse_callback(event, x, y, flags, param):
    """Gerenciador de cliques de mouse nos botões da interface"""
    global menu_open, sub_menu, is_recording, video_writer, motion_detection
    global flip_h, flip_v, rotation_angle, prev_gray_frame, camera_ip, cap, exposure_manual, exposure_val

    if event == cv2.EVENT_LBUTTONDOWN:
        # Clique no Botao de Menu (Icone de Hamburguer: X: 8 a 36, Y: 8 a 34)
        if 8 <= x <= 36 and 8 <= y <= 34:
            menu_open = not menu_open
            sub_menu = None
            return

        if menu_open:
            if sub_menu is None:
                # Opcao 1: Foto (Y: 45 a 67)
                if 8 <= x <= 142 and 45 <= y <= 67:
                    param['take_photo'] = True

                # Opcao 2: Gravar Video (Y: 71 a 93)
                elif 8 <= x <= 142 and 71 <= y <= 93:
                    is_recording = not is_recording

                # Opcao 3: Deteccao Movimento (Y: 97 a 119)
                elif 8 <= x <= 142 and 97 <= y <= 119:
                    motion_detection = not motion_detection
                    prev_gray_frame = None

                # Opcao 4: Configuracoes (Y: 123 a 145)
                elif 8 <= x <= 142 and 123 <= y <= 145:
                    sub_menu = 'config'

            elif sub_menu == 'config':
                # Botao Voltar (Y: 45 a 63)
                if 8 <= x <= 142 and 45 <= y <= 63:
                    sub_menu = None

                # Botao Inverter Horizontal (Y: 66 a 84)
                elif 8 <= x <= 142 and 66 <= y <= 84:
                    flip_h = not flip_h
                    save_config()

                # Botao Inverter Vertical (Y: 87 a 105)
                elif 8 <= x <= 142 and 87 <= y <= 105:
                    flip_v = not flip_v
                    save_config()

                # Rotacao 0 deg (Y: 108 a 124, X: 8 a 38)
                elif 8 <= x <= 38 and 108 <= y <= 124:
                    rotation_angle = 0
                    prev_gray_frame = None
                    save_config()
                    param['need_resize'] = True

                # Rotacao 90 deg (Y: 108 a 124, X: 41 a 71)
                elif 41 <= x <= 71 and 108 <= y <= 124:
                    rotation_angle = 90
                    prev_gray_frame = None
                    save_config()
                    param['need_resize'] = True

                # Rotacao 180 deg (Y: 108 a 124, X: 74 a 104)
                elif 74 <= x <= 104 and 108 <= y <= 124:
                    rotation_angle = 180
                    prev_gray_frame = None
                    save_config()
                    param['need_resize'] = True

                # Rotacao 270 deg (Y: 108 a 124, X: 107 a 137)
                elif 107 <= x <= 137 and 108 <= y <= 124:
                    rotation_angle = 270
                    prev_gray_frame = None
                    save_config()
                    param['need_resize'] = True

                # Exposicao AUTO / MANUAL (Y: 127 a 145)
                elif 8 <= x <= 142 and 127 <= y <= 145:
                    exposure_manual = not exposure_manual
                    save_config()

                # Botao - Exp (Y: 148 a 166, X: 8 a 72)
                elif 8 <= x <= 72 and 148 <= y <= 166:
                    if exposure_manual:
                        exposure_val = max(-10, exposure_val - 1)
                        save_config()

                # Botao + Exp (Y: 148 a 166, X: 75 a 142)
                elif 75 <= x <= 142 and 148 <= y <= 166:
                    if exposure_manual:
                        exposure_val = min(10, exposure_val + 1)
                        save_config()

                # Botao Rede / IPs (Y: 169 a 189)
                elif 8 <= x <= 142 and 169 <= y <= 189:
                    sub_menu = 'scanner'
                    start_network_scan()

            elif sub_menu == 'scanner':
                # Botao Voltar (Y: 45 a 65) -> Volta para Configuracoes
                if 8 <= x <= 142 and 45 <= y <= 65:
                    sub_menu = 'config'

                # Botao Mudar IP Manualmente (Y: 69 a 89)
                elif 8 <= x <= 142 and 69 <= y <= 89:
                    prompt_new_ip()

                # Botao Escanear Novamente (Y: 93 a 113)
                elif 8 <= x <= 142 and 93 <= y <= 113:
                    if not is_scanning:
                        start_network_scan()

                # Selecao de IP da lista clicavel
                else:
                    max_show = min(5, len(discovered_devices))
                    for idx in range(max_show):
                        item_y_start = 129 + (idx * 16)
                        item_y_end = item_y_start + 14
                        if 8 <= x <= 142 and item_y_start <= y <= item_y_end:
                            selected_ip, _ = discovered_devices[idx]
                            if camera_ip != selected_ip:
                                camera_ip = selected_ip
                                save_config()
                                print(f"[SCANNER] Novo IP selecionado: {camera_ip}")
                                if cap is not None:
                                    cap.release()
                                    cap = None
                            break

def main():
    global stop_threads, video_writer, cap, prev_gray_frame, is_recording

    window_name = "Visualizador de Camera IP"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

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

            # Redimensiona o frame para bater exatamente com a dimensao da janela
            canvas_w, canvas_h = (450, 600) if rotation_angle in [90, 270] else (960, 540)
            if frame.shape[1] != canvas_w or frame.shape[0] != canvas_h:
                frame = cv2.resize(frame, (canvas_w, canvas_h))

            # Ajuste de Exposicao Manual
            if exposure_manual and exposure_val != 0:
                factor = 1.0 + (exposure_val * 0.1)
                frame = cv2.convertScaleAbs(frame, alpha=factor, beta=0)

            display_frame = frame.copy()

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

        # Botao Principal de Menu (Icone Hamburguer ultra compacto)
        cv2.rectangle(display_frame, (8, 8), (36, 34), (40, 40, 40), -1)
        cv2.rectangle(display_frame, (8, 8), (36, 34), (180, 180, 180), 1)
        cv2.line(display_frame, (13, 14), (31, 14), (255, 255, 255), 2)
        cv2.line(display_frame, (13, 21), (31, 21), (255, 255, 255), 2)
        cv2.line(display_frame, (13, 28), (31, 28), (255, 255, 255), 2)

        # Desenho da Interface de Menus (Ultra Compacta: Largura 140px)
        if menu_open:
            max_menu_y = 150
            if sub_menu == 'config':
                max_menu_y = 195
            elif sub_menu == 'scanner':
                max_show_items = min(5, len(discovered_devices))
                max_menu_y = 129 + (max_show_items * 16) + 10

            cv2.rectangle(display_frame, (5, 38), (145, max_menu_y), (20, 20, 25), -1)
            cv2.rectangle(display_frame, (5, 38), (145, max_menu_y), (80, 80, 100), 1)

            if sub_menu is None:
                # Menu Principal
                cv2.rectangle(display_frame, (8, 45), (142, 67), (45, 45, 55), -1)
                cv2.putText(display_frame, "Tirar Foto", (14, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1)

                rec_bg = (40, 40, 120) if is_recording else (45, 45, 55)
                cv2.rectangle(display_frame, (8, 71), (142, 93), rec_bg, -1)
                cv2.putText(display_frame, "Parar Rec" if is_recording else "Gravar Video", (14, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1)

                mot_bg = (40, 120, 40) if motion_detection else (45, 45, 55)
                cv2.rectangle(display_frame, (8, 97), (142, 119), mot_bg, -1)
                cv2.putText(display_frame, "Det. Movimento", (14, 112), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1)

                cv2.rectangle(display_frame, (8, 123), (142, 145), (45, 45, 55), -1)
                cv2.putText(display_frame, "Configuracoes >", (14, 138), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1)

            elif sub_menu == 'config':
                cv2.rectangle(display_frame, (8, 45), (142, 63), (35, 35, 45), -1)
                cv2.putText(display_frame, "< Voltar", (14, 57), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (200, 200, 200), 1)

                bg_h = (40, 120, 40) if flip_h else (45, 45, 55)
                cv2.rectangle(display_frame, (8, 66), (142, 84), bg_h, -1)
                cv2.putText(display_frame, "Inv. Horiz", (14, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (255, 255, 255), 1)

                bg_v = (40, 120, 40) if flip_v else (45, 45, 55)
                cv2.rectangle(display_frame, (8, 87), (142, 105), bg_v, -1)
                cv2.putText(display_frame, "Inv. Vert", (14, 99), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (255, 255, 255), 1)

                # Seletor de Rotacao
                angles = [0, 90, 180, 270]
                x_starts = [8, 41, 74, 107]
                for idx_ang, ang in enumerate(angles):
                    x_s = x_starts[idx_ang]
                    bg_ang = (40, 120, 40) if rotation_angle == ang else (45, 45, 55)
                    cv2.rectangle(display_frame, (x_s, 108), (x_s + 30, 124), bg_ang, -1)
                    cv2.putText(display_frame, f"{ang}", (x_s + 3, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (255, 255, 255), 1)

                # Exposicao
                bg_exp = (40, 120, 40) if exposure_manual else (45, 45, 55)
                cv2.rectangle(display_frame, (8, 127), (142, 145), bg_exp, -1)
                cv2.putText(display_frame, f"Exp: {'MAN' if exposure_manual else 'AUTO'}", (14, 139), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (255, 255, 255), 1)

                cv2.rectangle(display_frame, (8, 148), (72, 166), (45, 45, 55), -1)
                cv2.putText(display_frame, "- Exp", (12, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (255, 255, 255), 1)
                cv2.rectangle(display_frame, (75, 148), (142, 166), (45, 45, 55), -1)
                cv2.putText(display_frame, f"+ Exp({exposure_val})", (78, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (255, 255, 255), 1)

                cv2.rectangle(display_frame, (8, 169), (142, 189), (45, 45, 55), -1)
                cv2.putText(display_frame, "Rede e IP >", (14, 182), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (255, 255, 255), 1)

            elif sub_menu == 'scanner':
                cv2.rectangle(display_frame, (8, 45), (142, 65), (35, 35, 45), -1)
                cv2.putText(display_frame, "< Voltar", (14, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (200, 200, 200), 1)

                cv2.rectangle(display_frame, (8, 69), (142, 89), (60, 40, 100), -1)
                cv2.putText(display_frame, "Mudar IP", (14, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (255, 255, 255), 1)

                bg_scan = (35, 35, 45) if is_scanning else (40, 110, 40)
                txt_scan = "Buscando..." if is_scanning else "Escanear Rede"
                cv2.rectangle(display_frame, (8, 93), (142, 113), bg_scan, -1)
                cv2.putText(display_frame, txt_scan, (14, 106), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (240, 240, 240), 1)

                y_pos = 129
                cv2.putText(display_frame, f"IPs: {len(discovered_devices)}", (10, 123), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (0, 255, 255), 1)
                
                max_show = min(5, len(discovered_devices))
                for idx in range(max_show):
                    ip_addr, _ = discovered_devices[idx]
                    is_active_ip = (ip_addr == camera_ip)
                    
                    color = (0, 255, 0) if is_active_ip else (220, 220, 220)
                    prefix_icon = ">" if is_active_ip else ""
                    
                    cv2.rectangle(display_frame, (8, y_pos - 8), (142, y_pos + 6), (50, 50, 60) if is_active_ip else (30, 30, 38), -1)
                    cv2.putText(display_frame, f"{prefix_icon}{ip_addr}", (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.30, color, 1)
                    y_pos += 16

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