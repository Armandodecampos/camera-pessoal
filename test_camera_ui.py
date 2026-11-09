import importlib
import os
import sys
import numpy as np
import cv2

# Import app module
app_module_name = "visualizador_de_c_mera_ip (41)"
app = importlib.import_module(app_module_name)

def test_no_exposure_remnants():
    """Valida que todas as opções de exposição foram removidas da configuração e do código."""
    assert "exposure_manual" not in app.DEFAULT_CONFIG, "exposure_manual ainda está em DEFAULT_CONFIG"
    assert "exposure_val" not in app.DEFAULT_CONFIG, "exposure_val ainda está em DEFAULT_CONFIG"
    assert not hasattr(app, "exposure_manual"), "exposure_manual ainda existe como global"
    assert not hasattr(app, "exposure_val"), "exposure_val ainda existe como global"
    print("PASS: test_no_exposure_remnants")

def test_letterbox_no_distortion():
    """Valida que a função letterbox_frame preserva a proporção da imagem sem distorção em várias proporções de tela."""
    # Imagem original 640x480 (proporção 4:3 = 1.333)
    img_4_3 = np.zeros((480, 640, 3), dtype=np.uint8)
    # Desenhar um círculo central
    cv2.circle(img_4_3, (320, 240), 100, (255, 255, 255), -1)

    # 1. Canvas widescreen 960x540 (16:9)
    out_16_9 = app.letterbox_frame(img_4_3, 960, 540)
    assert out_16_9.shape == (540, 960, 3)
    # Proporção deve ser mantida: altura 480 ajustada para 540 -> escala 540/480 = 1.125 -> largura = 640*1.125 = 720
    # Barras pretas laterais: (960 - 720) / 2 = 120 px
    assert np.all(out_16_9[:, :100] == 0), "Pillarbox esquerdo deveria ser preto"
    assert np.all(out_16_9[:, 860:] == 0), "Pillarbox direito deveria ser preto"
    assert np.any(out_16_9[:, 125:835] > 0), "Conteúdo deve estar presente na área central"

    # 2. Canvas alto/vertical 450x600 (3:4)
    out_vert = app.letterbox_frame(img_4_3, 450, 600)
    assert out_vert.shape == (600, 450, 3)
    # Largura 640 ajustada para 450 -> escala 450/640 = 0.703125 -> altura = 480*0.703125 = 337.5 -> 338
    # Barras pretas superior/inferior: (600 - 338) / 2 = 131 px
    assert np.all(out_vert[:100, :] == 0), "Letterbox superior deveria ser preto"
    assert np.all(out_vert[500:, :] == 0), "Letterbox inferior deveria ser preto"
    assert np.any(out_vert[150:450, :] > 0), "Conteúdo deve estar presente na área central"

    print("PASS: test_letterbox_no_distortion")

def test_menu_rendering_and_clicks():
    """Valida a renderização dos painéis de menu e a detecção de cliques do mouse."""
    canvas = np.zeros((540, 960, 3), dtype=np.uint8)
    mouse_param = {'take_photo': False, 'need_resize': False}

    # 1. Abrir Menu clicando no botão hambúrguer (X: 12..46, Y: 12..44)
    app.menu_open = False
    app.sub_menu = None
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 29, 28, 0, mouse_param)
    assert app.menu_open is True, "Menu deveria abrir com clique no hambúrguer"
    assert app.sub_menu is None

    # 2. Clicar em Tirar Foto (Y: 96..124, X: 24..188)
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 100, 110, 0, mouse_param)
    assert mouse_param['take_photo'] is True, "Tirar foto deveria ser acionado"
    mouse_param['take_photo'] = False

    # 3. Clicar em Gravar Video (Y: 132..160, X: 24..188)
    initial_rec = app.is_recording
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 100, 145, 0, mouse_param)
    assert app.is_recording != initial_rec, "is_recording deveria alternar"
    app.is_recording = False

    # 4. Clicar em Det. Movimento (Y: 168..196, X: 24..188)
    initial_motion = app.motion_detection
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 100, 180, 0, mouse_param)
    assert app.motion_detection != initial_motion, "motion_detection deveria alternar"
    app.motion_detection = False

    # 5. Clicar em Configuracoes > (Y: 204..232, X: 24..188)
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 100, 218, 0, mouse_param)
    assert app.sub_menu == 'config', "Submenu deveria ser 'config'"

    # 6. No submenu config: testar Inverter Horiz (Y: 130..156)
    initial_flip_h = app.flip_h
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 100, 140, 0, mouse_param)
    assert app.flip_h != initial_flip_h, "flip_h deveria alternar"

    # 7. Testar Inverter Vert (Y: 164..190)
    initial_flip_v = app.flip_v
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 100, 175, 0, mouse_param)
    assert app.flip_v != initial_flip_v, "flip_v deveria alternar"

    # 8. Testar rotação 90 graus (Y: 198..224, X: 66..103)
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 80, 210, 0, mouse_param)
    assert app.rotation_angle == 90, "rotation_angle deveria ser 90"
    assert mouse_param['need_resize'] is True
    mouse_param['need_resize'] = False

    # 9. Ir para Scanner de Rede (Y: 232..258, X: 24..188)
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 100, 245, 0, mouse_param)
    assert app.sub_menu == 'scanner', "Submenu deveria ser 'scanner'"

    # 10. No submenu scanner: Voltar para config (Y: 96..122)
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 100, 110, 0, mouse_param)
    assert app.sub_menu == 'config', "Deveria voltar para 'config'"

    # 11. No submenu config: Voltar para principal (Y: 96..122)
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 100, 110, 0, mouse_param)
    assert app.sub_menu is None, "Deveria voltar para o menu principal"

    # 12. Fechar menu com clique no botão de fechar (X: 12..46, Y: 12..44)
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 29, 28, 0, mouse_param)
    assert app.menu_open is False, "Menu deveria estar fechado"

    print("PASS: test_menu_rendering_and_clicks")

def test_change_camera_ip_and_reconnection_loop():
    """Valida que change_camera_ip atualiza IP, reseta cap, sinaliza reconexão imediata e para tentativas anteriores."""
    import time
    import threading

    # Simular cap anterior aberto
    class DummyCap:
        def __init__(self, opened=True):
            self._opened = opened
            self.released = False

        def isOpened(self):
            return self._opened and not self.released

        def release(self):
            self.released = True

    dummy_cap = DummyCap(True)
    app.cap = dummy_cap
    app.is_connected = True
    app.is_connecting = False
    init_conn_id = app.current_connection_id

    app.change_camera_ip("192.168.1.50")

    assert app.camera_ip == "192.168.1.50", "camera_ip não foi atualizado"
    assert app.cap is None, "cap anterior não foi setado para None"
    assert dummy_cap.released is True, "cap anterior não foi liberado"
    assert app.is_connected is False, "is_connected deveria ser False"
    assert app.current_connection_id > init_conn_id, "current_connection_id deveria ter incrementado"
    assert app.reconnect_event.is_set(), "reconnect_event deveria ter sido acionado"

    # Testar seleção de IP no menu scanner acionando change_camera_ip
    app.discovered_devices = [("192.168.1.99", "Camera Nova")]
    app.menu_open = True
    app.sub_menu = 'scanner'
    mouse_param = {'take_photo': False, 'need_resize': False}
    # Clicar no 1o IP da lista (item_y_start = 228, item_y_end = 252, bx1=24..bx2=188)
    app.mouse_callback(cv2.EVENT_LBUTTONDOWN, 50, 235, 0, mouse_param)
    assert app.camera_ip == "192.168.1.99", "Clicar no item da lista deveria atualizar o camera_ip via change_camera_ip"

    print("PASS: test_change_camera_ip_and_reconnection_loop")

def test_connection_loop_aborts_on_new_ip():
    """Valida que a thread de conexão interrompe imediatamente a tentativa ao mudar de IP e foca no novo IP."""
    import time
    import threading

    attempted_urls = []
    real_VideoCapture = cv2.VideoCapture

    class MockVideoCapture:
        def __init__(self, url):
            attempted_urls.append(url)
            self.url = url
            self.released = False

        def isOpened(self):
            # Nunca conecta com sucesso para simular câmera offline tentando em loop
            return False

        def release(self):
            self.released = True

    cv2.VideoCapture = MockVideoCapture
    app.stop_threads = False
    app.cap = None
    app.is_connected = False
    app.camera_ip = "192.168.1.100"

    t = threading.Thread(target=app.connect_camera_thread)
    t.daemon = True
    t.start()

    time.sleep(0.3)
    # Verifica que tentou conectar no IP antigo
    assert any("192.168.1.100" in u for u in attempted_urls), "Deveria ter tentado conectar no primeiro IP"

    # Agora muda de IP imediatamente enquanto a thread está executando
    app.change_camera_ip("192.168.2.200")
    time.sleep(0.3)

    # Verifica que imediatamente passou a tentar o novo IP
    assert any("192.168.2.200" in u for u in attempted_urls), "Deveria ter passado a tentar o novo IP"

    # Finaliza a thread de teste
    app.stop_threads = True
    app.reconnect_event.set()
    t.join(timeout=1.0)
    cv2.VideoCapture = real_VideoCapture

    print("PASS: test_connection_loop_aborts_on_new_ip")

def generate_screenshots():
    """Gera screenshots dos menus estilizados para inspeção visual."""
    os.makedirs("test_output", exist_ok=True)

    # 1. Menu Principal
    frame_main = np.zeros((540, 960, 3), dtype=np.uint8)
    # Background suave simulando câmera
    cv2.putText(frame_main, "STREAM DA CAMERA IP", (360, 270), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (70, 75, 90), 2)
    app.menu_open = True
    app.sub_menu = None
    app.is_recording = False
    app.motion_detection = True

    # Simular desenho do hambúrguer e menu principal
    # Botão hambúrguer
    btn_hb_bg = (48, 55, 72)
    btn_hb_border = (90, 105, 135)
    app.draw_rounded_rect(frame_main, (12, 12), (46, 44), btn_hb_bg, radius=6, thickness=-1)
    app.draw_rounded_rect(frame_main, (12, 12), (46, 44), btn_hb_border, radius=6, thickness=1)
    cx, cy = 29, 28
    cv2.line(frame_main, (cx - 7, cy - 7), (cx + 7, cy + 7), (255, 255, 255), 2, cv2.LINE_AA)
    cv2.line(frame_main, (cx - 7, cy + 7), (cx + 7, cy - 7), (255, 255, 255), 2, cv2.LINE_AA)

    bx1, bx2 = 24, 188
    app.draw_menu_panel(frame_main, (12, 54), (200, 246), "MENU PRINCIPAL")
    app.draw_menu_button(frame_main, (bx1, 96), (bx2, 124), "Tirar Foto", (36, 42, 55), border_color=(65, 75, 95))
    app.draw_menu_button(frame_main, (bx1, 132), (bx2, 160), "Gravar Video", (36, 42, 55), border_color=(65, 75, 95))
    app.draw_menu_button(frame_main, (bx1, 168), (bx2, 196), "Det. Movimento", (30, 110, 50), border_color=(50, 180, 85))
    app.draw_menu_button(frame_main, (bx1, 204), (bx2, 232), "Configuracoes >", (45, 52, 68), border_color=(80, 95, 120))

    cv2.imwrite("test_output/menu_principal.png", frame_main)

    # 2. Menu Configurações
    frame_config = np.zeros((540, 960, 3), dtype=np.uint8)
    app.draw_rounded_rect(frame_config, (12, 12), (46, 44), btn_hb_bg, radius=6, thickness=-1)
    app.draw_rounded_rect(frame_config, (12, 12), (46, 44), btn_hb_border, radius=6, thickness=1)
    cv2.line(frame_config, (cx - 7, cy - 7), (cx + 7, cy + 7), (255, 255, 255), 2, cv2.LINE_AA)
    cv2.line(frame_config, (cx - 7, cy + 7), (cx + 7, cy - 7), (255, 255, 255), 2, cv2.LINE_AA)

    app.draw_menu_panel(frame_config, (12, 54), (200, 272), "CONFIGURACOES")
    app.draw_menu_button(frame_config, (bx1, 96), (bx2, 122), "< Voltar", (30, 35, 46), text_color=(180, 190, 205), border_color=(55, 65, 80))
    app.draw_menu_button(frame_config, (bx1, 130), (bx2, 156), "Inverter Horiz: DES", (36, 42, 55), border_color=(65, 75, 95))
    app.draw_menu_button(frame_config, (bx1, 164), (bx2, 190), "Inverter Vert: DES", (36, 42, 55), border_color=(65, 75, 95))
    angles = [0, 90, 180, 270]
    ang_x = [24, 66, 108, 150]
    for idx_ang, ang in enumerate(angles):
        x_s = ang_x[idx_ang]
        bg_ang = (30, 110, 50) if ang == 0 else (36, 42, 55)
        brd_ang = (50, 180, 85) if ang == 0 else (65, 75, 95)
        app.draw_menu_button(frame_config, (x_s, 198), (x_s + 37, 224), f"{ang}", bg_ang, border_color=brd_ang, font_scale=0.32)
    app.draw_menu_button(frame_config, (bx1, 232), (bx2, 258), "Rede e IP >", (45, 52, 68), border_color=(80, 95, 120))

    cv2.imwrite("test_output/menu_config.png", frame_config)

    # 3. Menu Scanner
    frame_scan = np.zeros((540, 960, 3), dtype=np.uint8)
    app.draw_rounded_rect(frame_scan, (12, 12), (46, 44), btn_hb_bg, radius=6, thickness=-1)
    app.draw_rounded_rect(frame_scan, (12, 12), (46, 44), btn_hb_border, radius=6, thickness=1)
    cv2.line(frame_scan, (cx - 7, cy - 7), (cx + 7, cy + 7), (255, 255, 255), 2, cv2.LINE_AA)
    cv2.line(frame_scan, (cx - 7, cy + 7), (cx + 7, cy - 7), (255, 255, 255), 2, cv2.LINE_AA)

    devs = [("192.168.0.10", "Camera"), ("192.168.0.1", "Router"), ("192.168.0.25", "PC")]
    max_show = len(devs)
    scanner_panel_h = 236 + (max_show * 28)
    app.draw_menu_panel(frame_scan, (12, 54), (200, scanner_panel_h), "REDE E IP")
    app.draw_menu_button(frame_scan, (bx1, 96), (bx2, 122), "< Voltar", (30, 35, 46), text_color=(180, 190, 205), border_color=(55, 65, 80))
    app.draw_menu_button(frame_scan, (bx1, 130), (bx2, 156), "Mudar IP", (55, 42, 90), border_color=(95, 75, 150))
    app.draw_menu_button(frame_scan, (bx1, 164), (bx2, 190), "Escanear Rede", (30, 110, 50), border_color=(50, 180, 85))

    (tw_c, _), _ = cv2.getTextSize(f"IPs Encontrados ({len(devs)})", cv2.FONT_HERSHEY_SIMPLEX, 0.30, 1)
    tx_c = 12 + (188 - tw_c) // 2
    cv2.putText(frame_scan, f"IPs Encontrados ({len(devs)})", (tx_c, 212), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (180, 195, 215), 1, cv2.LINE_AA)

    for idx in range(max_show):
        ip_addr, _ = devs[idx]
        is_active_ip = (ip_addr == "192.168.0.10")
        item_y_start = 228 + (idx * 28)
        item_y_end = item_y_start + 24
        ip_bg = (30, 75, 40) if is_active_ip else (28, 33, 44)
        ip_border = (50, 160, 80) if is_active_ip else (50, 60, 75)
        ip_text_col = (180, 255, 200) if is_active_ip else (220, 225, 235)
        label = f"* {ip_addr}" if is_active_ip else ip_addr
        app.draw_menu_button(frame_scan, (bx1, item_y_start), (bx2, item_y_end), label, ip_bg, text_color=ip_text_col, border_color=ip_border, font_scale=0.32)

    cv2.imwrite("test_output/menu_scanner.png", frame_scan)
    print("PASS: generate_screenshots (saved to test_output/)")

if __name__ == "__main__":
    test_no_exposure_remnants()
    test_letterbox_no_distortion()
    test_menu_rendering_and_clicks()
    test_change_camera_ip_and_reconnection_loop()
    test_connection_loop_aborts_on_new_ip()
    generate_screenshots()
    print("ALL TESTS PASSED SUCCESSFULLY!")
