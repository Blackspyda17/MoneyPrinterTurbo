import argparse
import subprocess
import os
import tempfile

def run_ffmpeg(cmd):
    print(f"\nEjecutando:\n$ {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("\nERROR: ffmpeg falló al intentar unir los videos.")
        print("Nota: Si los videos tienen diferente resolución, framerate o codecs, el método '-c copy' puede fallar.")
        print("En ese caso, puedes usar un re-encode modificando este script.")
        exit(result.returncode)

def concat_videos(vid1, vid2, output_path):
    # Usamos el demuxer 'concat' de ffmpeg que es súper rápido porque no re-encodea el video (solo copia los streams).
    # Requisito: Los videos deben tener el mismo formato (codec, resolución, framerate).
    # Como son screen recordings de la misma app, esto debería funcionar perfectamente.
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        # ffmpeg requiere rutas absolutas o relativas al archivo de texto
        f.write(f"file '{os.path.abspath(vid1)}'\n")
        f.write(f"file '{os.path.abspath(vid2)}'\n")
        list_file = f.name
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_path
    ]
    
    try:
        run_ffmpeg(cmd)
    finally:
        # Limpiar el archivo de texto temporal
        os.remove(list_file)

if __name__ == "__main__":
    # Rellena aquí las rutas de tus videos:
    vid1_path = '/Users/andres/Desktop/Simulator Screen Recording - Pro Max 16 With Wear - 2026-04-23 at 16.28.25.mov'
    vid2_path = '/Users/andres/Desktop/Simulator Screen Recording - Pro Max 16 With Wear - 2026-04-23 at 16.29.19.mov'
    output_path = "/Users/andres/Documents/dev/dreamIQ-images/videos/final_screenrecord.mp4"
    
    if not os.path.exists(vid1_path):
        print(f"Error: No se encuentra el video 1: {vid1_path}")
        exit(1)
    if not os.path.exists(vid2_path):
        print(f"Error: No se encuentra el video 2: {vid2_path}")
        exit(1)
        
    # Crear directorio de salida si no existe
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        
    concat_videos(vid1_path, vid2_path, output_path)
    print(f"\n✅ ¡Videos unidos con éxito!\nGuardado en: {output_path}")
