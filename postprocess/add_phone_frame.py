import os
import subprocess
import sys

def add_frame(video_path, frame_path, output_path, screen_x, screen_y, screen_w, screen_h, target_w=1080, target_h=1920):
    """
    Toma un video y lo pone debajo de un frame PNG con transparencia.
    Luego lo coloca en un fondo negro de tamaño target_w x target_h para
    que coincida con la resolución del video base y xfade funcione.
    """
    
    # Primero obtenemos el tamaño total del frame PNG
    cmd_dim = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", frame_path]
    result = subprocess.run(cmd_dim, capture_output=True, text=True)
    
    if result.returncode != 0 or not result.stdout.strip():
        print("Error: No se pudo obtener las dimensiones del frame.")
        sys.exit(1)
        
    frame_w, frame_h = result.stdout.strip().split('x')
    
    # Construir el filtro complejo de ffmpeg:
    # 1. Escala el video (0:v) al hueco del celular.
    # 2. Le agrega el padding para igualar el tamaño del frame PNG.
    # 3. Sobrepone el frame PNG (1:v) sobre el video.
    # 4. Escala el conjunto resultante para que encaje en la resolución final (target_w x target_h).
    # 5. Rellena los bordes con negro para completar 1080x1920.
    
    filter_complex = (
        f"[0:v]scale={screen_w}:{screen_h}:force_original_aspect_ratio=increase,"
        f"crop={screen_w}:{screen_h}[scaled];"
        f"[scaled]pad={frame_w}:{frame_h}:{screen_x}:{screen_y}:color=black@0[padded];"
        f"[padded][1:v]overlay=0:0[framed];"
        f"[framed]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:-1:-1:color=black[out]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", frame_path,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a?", # Si el video original tiene audio, lo copiamos
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "copy",
        output_path
    ]
    
    print(f"\nEjecutando:\n$ {' '.join(cmd)}\n")
    subprocess.run(cmd)

if __name__ == "__main__":
    video = "/Users/andres/Documents/dev/dreamIQ-images/videos/final_screenrecord.mp4"
    frame = "/Users/andres/Documents/dev/dreamIQ-images/videos/frame-iphone-16-pro-max.png"
    output = "/Users/andres/Documents/dev/dreamIQ-images/videos/final_screenrecord_framed.mp4"
    
    # =========================================================================
    # AJUSTA ESTOS VALORES SEGÚN EL ÁREA TRANSPARENTE DE TU FRAME PNG
    # (He puesto valores iniciales estimados basándome en que el frame es 364x750)
    # =========================================================================
    screen_w = 336   # Ancho del área visible de la pantalla (en píxeles)
    screen_h = 722   # Alto del área visible de la pantalla
    screen_x = 14    # Margen izquierdo (desde el borde del PNG hasta donde empieza la pantalla)
    screen_y = 14    # Margen superior (desde arriba hasta donde empieza la pantalla)
    
    if not os.path.exists(video):
        print(f"Error: No se encontró el video:\n{video}")
        sys.exit(1)
    if not os.path.exists(frame):
        print(f"Error: No se encontró el frame:\n{frame}")
        sys.exit(1)
        
    add_frame(video, frame, output, screen_x, screen_y, screen_w, screen_h)
    
    print(f"\n✅ Video con frame guardado en: {output}")
    print("---------------------------------------------------------")
    print("Revisa el video final. Si la grabación de pantalla no encaja bien ")
    print("en el marco (si sobra espacio negro o se come los bordes del celular),")
    print("regresa a este script, ajusta los valores de screen_w, screen_h, screen_x")
    print("y screen_y, y vuelve a ejecutarlo.")
