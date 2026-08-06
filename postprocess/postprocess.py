"""
postprocess.py — Post-procesamiento de videos generados por MoneyPrinterTurbo
=============================================================================

DESCRIPCIÓN
-----------
Script para aplicar post-procesamiento a videos generados por MoneyPrinterTurbo.
Permite insertar screen recordings o screenshots (con marco de teléfono) en
momentos específicos del video con transiciones animadas, y agregar una imagen
de end card con fade-in al final.

IMÁGENES EN CLIPS
-----------------
Los clips pueden ser video (.mp4) o imagen estática (.png, .jpg, .jpeg, .webp).
Para imágenes, agrega 'duration' en el TOML para indicar cuántos segundos
mostrarla (obligatorio — no se puede inferir de la imagen):

    [[clips]]
    file      = "./screenshots/archetype_framed.png"
    duration  = 4.0
    insert_at = 32.0

USO
---
Desde la carpeta marketing/video-generation/:

    # Ver qué comandos ffmpeg se ejecutarían (sin modificar nada)
    python postprocess/postprocess.py postprocess/configs/mi_video.toml --dry-run

    # Generar clips de preview de ~10s alrededor de cada insertion point
    # (rápido — no re-encodea el video completo)
    python postprocess/postprocess.py postprocess/configs/mi_video.toml --preview

    # Render final completo
    python postprocess/postprocess.py postprocess/configs/mi_video.toml

WORKFLOW RECOMENDADO
--------------------
1. Genera el video con MoneyPrinterTurbo (WebUI o API)
2. Copia postprocess/configs/template.toml → postprocess/configs/mi_video.toml
3. Edita el TOML: pon la ruta del video, los timestamps y archivos
4. Corre --preview para verificar que los timestamps son correctos
5. Corre el render final

TRANSICIONES DISPONIBLES (xfade ffmpeg)
----------------------------------------
Movimiento:
  slideup      — el nuevo clip sube desde abajo (recomendado para phone screens)
  slidedown    — el nuevo clip baja desde arriba
  slideleft    — el nuevo clip entra desde la derecha
  slideright   — el nuevo clip entra desde la izquierda
  smoothup     — variante suave de slideup con ease in/out
  smoothdown   — variante suave de slidedown
  smoothleft   — variante suave de slideleft
  smoothright  — variante suave de slideright

Fundidos:
  fade         — cross-dissolve entre los dos clips (más cinematográfico)
  fadeblack    — funde a negro antes de mostrar el nuevo clip
  fadewhite    — funde a blanco antes de mostrar el nuevo clip

Barras:
  wipeleft     — barra que barre de derecha a izquierda
  wiperight    — barra que barre de izquierda a derecha
  wipeup       — barra que barre de abajo hacia arriba
  wipedown     — barra que barre de arriba hacia abajo

Sin transición:
  none         — corte directo (hard cut)

REQUISITOS
----------
- ffmpeg y ffprobe instalados y en el PATH
- Python 3.8+
- pip install toml  (o Python 3.11+ que incluye tomllib nativo)
"""

import argparse
import os
import subprocess
import sys
import tempfile

# Intentar importar toml (Python 3.11+ tiene tomllib nativo; versiones anteriores necesitan el paquete toml)
try:
    import tomllib  # Python 3.11+
    def _load_toml(path):
        with open(path, "rb") as f:
            return tomllib.load(f)
except ImportError:
    try:
        import toml  # pip install toml
        def _load_toml(path):
            return toml.load(path)
    except ImportError:
        print("ERROR: Necesitas instalar el paquete 'toml': pip install toml")
        sys.exit(1)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# Transiciones válidas de xfade en ffmpeg
VALID_TRANSITIONS = {
    "slideup", "slidedown", "slideleft", "slideright",
    "smoothup", "smoothdown", "smoothleft", "smoothright",
    "fade", "fadeblack", "fadewhite",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "none",
}


# ---------------------------------------------------------------------------
# Utilidades ffmpeg/ffprobe
# ---------------------------------------------------------------------------

def get_video_duration(path: str) -> float:
    """Obtiene la duración en segundos de un archivo de video usando ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe falló para '{path}': {result.stderr.strip()}")
    return float(result.stdout.strip())


def run_ffmpeg(cmd: list[str], dry_run: bool = False, label: str = "") -> None:
    """Ejecuta un comando ffmpeg. Si dry_run=True, solo lo imprime."""
    printable = " ".join(cmd)
    if label:
        print(f"\n[{label}]")
    print(f"  $ {printable}")
    if not dry_run:
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg falló (código {result.returncode})")


# ---------------------------------------------------------------------------
# Validación del config
# ---------------------------------------------------------------------------

def parse_config(toml_path: str) -> dict:
    """
    Lee y valida el archivo TOML de configuración.
    Retorna el dict de config con rutas absolutas resueltas.
    Lanza ValueError si hay campos inválidos o archivos que no existen.
    """
    # Resolver rutas relativas al directorio desde donde se ejecuta el script
    # (normalmente marketing/video-generation/)
    base_dir = os.getcwd()

    cfg = _load_toml(toml_path)

    # --- base_video ---
    if "base_video" not in cfg:
        raise ValueError("Falta 'base_video' en el config.")
    cfg["base_video"] = _resolve_path(cfg["base_video"], base_dir)
    if not os.path.exists(cfg["base_video"]):
        raise ValueError(f"base_video no encontrado: {cfg['base_video']}")

    # --- output ---
    if "output" not in cfg:
        raise ValueError("Falta 'output' en el config.")
    cfg["output"] = _resolve_path(cfg["output"], base_dir)
    os.makedirs(os.path.dirname(cfg["output"]) or ".", exist_ok=True)

    # --- clips (opcional pero frecuente) ---
    clips = cfg.get("clips", [])
    for i, clip in enumerate(clips):
        for key in ("file", "insert_at"):
            if key not in clip:
                raise ValueError(f"clips[{i}] le falta '{key}'.")
        clip["file"] = _resolve_path(clip["file"], base_dir)
        if not os.path.exists(clip["file"]):
            raise ValueError(f"clips[{i}].file no encontrado: {clip['file']}")

        ext = os.path.splitext(clip["file"])[1].lower()
        clip["is_image"] = ext in IMAGE_EXTENSIONS
        if clip["is_image"] and "duration" not in clip:
            raise ValueError(
                f"clips[{i}] es una imagen pero le falta 'duration' (en segundos)."
            )

        clip.setdefault("transition_in", "slideup")
        clip.setdefault("transition_out", "slidedown")
        clip.setdefault("transition_duration", 0.5)
        for key in ("transition_in", "transition_out"):
            if clip[key] not in VALID_TRANSITIONS:
                raise ValueError(
                    f"clips[{i}].{key} = '{clip[key]}' no es válido. "
                    f"Opciones: {sorted(VALID_TRANSITIONS)}"
                )
    # Ordenar clips por insert_at (de menor a mayor) para procesar en orden cronológico
    cfg["clips"] = sorted(clips, key=lambda c: c["insert_at"])

    # --- end_card (opcional) ---
    if "end_card" in cfg:
        ec = cfg["end_card"]
        if "file" not in ec:
            raise ValueError("end_card le falta 'file'.")
        ec["file"] = _resolve_path(ec["file"], base_dir)
        if not os.path.exists(ec["file"]):
            raise ValueError(f"end_card.file no encontrado: {ec['file']}")
        ec.setdefault("start_at", None)   # None = calcular automáticamente
        ec.setdefault("fade_duration", 3.0)

    return cfg


def _resolve_path(path: str, base_dir: str) -> str:
    """Convierte una ruta relativa en absoluta respecto a base_dir."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base_dir, path))


# ---------------------------------------------------------------------------
# Construcción de los comandos ffmpeg
# ---------------------------------------------------------------------------

def _image_to_video(image_path: str, duration: float, out: str,
                    dry_run: bool, label: str = "") -> None:
    """Convierte una imagen estática a un video corto de duración fija a 30fps."""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
               "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-an",
        out,
    ]
    run_ffmpeg(cmd, dry_run=dry_run, label=label or f"Imagen → video ({duration}s)")


def build_segment_commands(
    base_video: str,
    clips: list[dict],
    tmp_dir: str,
    dry_run: bool = False,
) -> list[str]:
    """
    Divide el video base y los screen recorders en segmentos,
    aplica xfade entre ellos y retorna la ruta del video resultado.

    Estrategia:
      Para cada clip a insertar, el video base se corta en:
        - seg_before: base[prev_end → insert_at + td/2]
        - seg_clip:   clip[0 → clip_duration] a 30fps
        - (el siguiente corte comienza en insert_at + clip_duration - td/2)
      Luego se aplica xfade entre cada par de segmentos.

    Retorna la ruta del video final (solo video, sin audio).
    """
    td_default = 0.5  # transition_duration por defecto si no se usa xfade

    base_dur = get_video_duration(base_video)
    seg_paths = []

    # Posición actual en el video base (avanza conforme procesamos clips)
    cursor = 0.0

    for i, clip in enumerate(clips):
        insert_at = clip["insert_at"]
        td = clip["transition_duration"]
        clip_dur = clip["duration"] if clip.get("is_image") else get_video_duration(clip["file"])

        if insert_at <= cursor:
            raise ValueError(
                f"clips[{i}] insert_at={insert_at}s se solapa con el clip anterior "
                f"(cursor en {cursor:.2f}s). Ajusta los timestamps."
            )

        # Si el clip es una imagen, convertirla a video primero
        if clip.get("is_image"):
            clip_as_video = os.path.join(tmp_dir, f"img_{i}_as_video.mp4")
            _image_to_video(clip["file"], clip_dur, clip_as_video, dry_run,
                            label=f"Imagen → video (clip {i+1})")
            clip_source = clip_as_video
        else:
            clip_source = clip["file"]

        # Segmento del video base antes del clip
        seg_before = os.path.join(tmp_dir, f"seg_{i}_before.mp4")
        end_before = insert_at + (td / 2 if clip["transition_in"] != "none" else 0)
        _encode_segment(base_video, cursor, end_before, seg_before, dry_run, label=f"Segmento base antes del clip {i+1}")
        seg_paths.append(seg_before)

        # Segmento del clip (screen recorder o imagen convertida) a 30fps
        seg_clip = os.path.join(tmp_dir, f"seg_{i}_clip.mp4")
        _encode_segment(clip_source, 0, clip_dur, seg_clip, dry_run,
                        label=f"Clip {i+1}", fps=30 if not clip.get("is_image") else None)
        seg_paths.append(seg_clip)

        # Mover cursor al punto de reanudación en el video base
        cursor = insert_at + clip_dur - (td / 2 if clip["transition_out"] != "none" else 0)

    # Segmento final del video base (desde el último cursor hasta el fin)
    seg_final = os.path.join(tmp_dir, "seg_final.mp4")
    _encode_segment(base_video, cursor, base_dur, seg_final, dry_run, label="Segmento base final")
    seg_paths.append(seg_final)

    # Aplicar xfade encadenado entre todos los segmentos
    output_video = os.path.join(tmp_dir, "video_composed.mp4")
    _apply_xfade_chain(seg_paths, clips, output_video, dry_run)

    return output_video


def _encode_segment(src: str, start: float, end: float, out: str,
                     dry_run: bool, label: str = "", fps: int = None):
    """Extrae un segmento de video entre start y end segundos."""
    cmd = ["ffmpeg", "-y"]
    cmd += ["-i", src]
    vf = f"trim=start={start}:end={end},setpts=PTS-STARTPTS"
    if fps:
        vf = f"fps={fps}," + vf
    cmd += ["-vf", vf, "-an", "-c:v", "libx264", "-crf", "18", "-preset", "fast", out]
    run_ffmpeg(cmd, dry_run=dry_run, label=label)


def _apply_xfade_chain(seg_paths: list[str], clips: list[dict],
                        output: str, dry_run: bool):
    """
    Encadena N segmentos con xfade.
    seg_paths alterna: [before_0, clip_0, before_1, clip_1, ..., final]
    clips define las transiciones entre cada par.
    """
    print("\n[Aplicando transiciones xfade]")

    if len(seg_paths) == 1:
        # Sin clips, solo copiar
        run_ffmpeg(["ffmpeg", "-y", "-i", seg_paths[0], "-c", "copy", output],
                   dry_run=dry_run)
        return

    cmd = ["ffmpeg", "-y"]
    for p in seg_paths:
        cmd += ["-i", p]

    # Calcular duraciones para los offsets de xfade
    # Necesitamos la duración real de cada segmento ya encodado
    # En dry_run usamos 0 como placeholder
    durations = []
    for p in seg_paths:
        if dry_run or not os.path.exists(p):
            durations.append(0.0)
        else:
            durations.append(get_video_duration(p))

    # Construir filtro xfade encadenado
    # Para N segmentos necesitamos N-1 transiciones
    # Los clips[i] definen la transición entre: before_i→clip_i y clip_i→before_{i+1}
    filter_parts = []
    prev_label = "0:v"
    cumulative_duration = durations[0]
    xfade_idx = 0

    for i, clip in enumerate(clips):
        td = clip["transition_duration"]

        # Transición: before_i → clip_i
        seg_clip_idx = i * 2 + 1
        trans_in = clip["transition_in"]
        if trans_in == "none":
            # Hard cut: concat sin xfade
            out_label = f"[xf{xfade_idx}]"
            filter_parts.append(
                f"[{prev_label}][{seg_clip_idx}:v]concat=n=2:v=1:a=0{out_label}"
            )
            cumulative_duration += durations[seg_clip_idx]
        else:
            offset = max(0, cumulative_duration - td)
            out_label = f"[xf{xfade_idx}]"
            filter_parts.append(
                f"[{prev_label}][{seg_clip_idx}:v]"
                f"xfade=transition={trans_in}:duration={td}:offset={offset:.4f}"
                f"{out_label}"
            )
            cumulative_duration += durations[seg_clip_idx] - td
        xfade_idx += 1
        prev_label = out_label[1:-1]  # quitar corchetes

        # Transición: clip_i → before_{i+1} (o final)
        next_seg_idx = i * 2 + 2
        trans_out = clip["transition_out"]
        if trans_out == "none":
            out_label = f"[xf{xfade_idx}]"
            filter_parts.append(
                f"[{prev_label}][{next_seg_idx}:v]concat=n=2:v=1:a=0{out_label}"
            )
            cumulative_duration += durations[next_seg_idx]
        else:
            offset = max(0, cumulative_duration - td)
            out_label = f"[xf{xfade_idx}]"
            filter_parts.append(
                f"[{prev_label}][{next_seg_idx}:v]"
                f"xfade=transition={trans_out}:duration={td}:offset={offset:.4f}"
                f"{out_label}"
            )
            cumulative_duration += durations[next_seg_idx] - td
        xfade_idx += 1
        prev_label = out_label[1:-1]

    # Renombrar el último label a [vout]
    last = filter_parts[-1]
    filter_parts[-1] = last.rsplit("[xf", 1)[0] + "[vout]"

    cmd += ["-filter_complex", ";".join(filter_parts)]
    cmd += ["-map", "[vout]", "-c:v", "libx264", "-crf", "18", "-preset", "fast", output]
    run_ffmpeg(cmd, dry_run=dry_run, label="Composición final con xfade")


def apply_end_card(video_path: str, end_card: dict, output: str,
                    base_video_dur: float, dry_run: bool):
    """
    Superpone la imagen end_card sobre el video con fade-in alpha.
    El resultado se guarda en output.
    """
    start_at = end_card.get("start_at")
    fade_dur = end_card.get("fade_duration", 3.0)

    # Si start_at no está definido, calcular automáticamente:
    # empieza fade_duration*2 segundos antes del fin del video
    if start_at is None:
        start_at = max(0, base_video_dur - fade_dur * 2)
        print(f"\n[End card] start_at no definido, usando {start_at:.1f}s "
              f"({fade_dur*2}s antes del fin del video)")

    video_dur = get_video_duration(video_path) if not dry_run else base_video_dur

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-loop", "1", "-i", end_card["file"],
        "-filter_complex",
        f"[1:v]scale=iw:ih,format=rgba,"
        f"fade=t=in:st={start_at}:d={fade_dur}:alpha=1[endcard];"
        f"[0:v][endcard]overlay=0:0[vout]",
        "-map", "[vout]", "-map", "0:a?",
        "-t", str(video_dur),
        "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-c:a", "copy",
        output,
    ]
    run_ffmpeg(cmd, dry_run=dry_run, label=f"End card (fade-in en {start_at:.1f}s)")


def mux_audio(video_only: str, original_video: str, output: str, dry_run: bool):
    """Combina el video procesado (sin audio) con el audio del video original."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_only,
        "-i", original_video,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "copy",
        "-shortest",
        output,
    ]
    run_ffmpeg(cmd, dry_run=dry_run, label="Agregar audio original")


# ---------------------------------------------------------------------------
# Modo Preview
# ---------------------------------------------------------------------------

def render_preview(base_video: str, clips: list[dict], tmp_dir: str):
    """
    Genera un clip de ~10s alrededor de cada insertion point para verificar
    timestamps sin tener que encodear el video completo.
    Abre cada preview automáticamente con el reproductor del sistema (macOS: open).
    """
    print("\n=== MODO PREVIEW ===")
    print("Generando clips de 10s alrededor de cada insertion point...\n")

    preview_files = []
    for i, clip in enumerate(clips):
        insert_at = clip["insert_at"]
        td = clip["transition_duration"]
        clip_dur = clip["duration"] if clip.get("is_image") else get_video_duration(clip["file"])

        # Ventana de preview: 3s antes del insert hasta 3s después del fin del clip
        preview_start = max(0, insert_at - 3)
        preview_duration = 3 + clip_dur + 3  # 3s antes + clip + 3s después

        out_preview = os.path.join(tmp_dir, f"preview_clip_{i+1}.mp4")

        # Segmento del video base antes del clip (solo los últimos 3s)
        seg_a = os.path.join(tmp_dir, f"prev_{i}_a.mp4")
        _encode_segment(base_video, preview_start, insert_at + td / 2, seg_a,
                         dry_run=False, label=f"Preview {i+1}: segmento base")

        # Clip — convertir imagen a video si aplica
        if clip.get("is_image"):
            img_video = os.path.join(tmp_dir, f"prev_{i}_img.mp4")
            _image_to_video(clip["file"], clip_dur, img_video, dry_run=False,
                            label=f"Preview {i+1}: imagen → video")
            clip_source = img_video
        else:
            clip_source = clip["file"]

        seg_b = os.path.join(tmp_dir, f"prev_{i}_b.mp4")
        _encode_segment(clip_source, 0, clip_dur, seg_b,
                         dry_run=False, fps=30 if not clip.get("is_image") else None,
                         label=f"Preview {i+1}: clip")

        # Segmento del video base después del clip (solo los primeros 3s)
        seg_c = os.path.join(tmp_dir, f"prev_{i}_c.mp4")
        resume_at = insert_at + clip_dur - td / 2
        _encode_segment(base_video, resume_at, resume_at + 3, seg_c,
                         dry_run=False, label=f"Preview {i+1}: segmento base después")

        # Aplicar xfade entry + exit
        trans_in = clip["transition_in"]
        trans_out = clip["transition_out"]
        a_dur = get_video_duration(seg_a)
        b_dur = get_video_duration(seg_b)

        filter_str = (
            f"[0:v][1:v]xfade=transition={trans_in}:duration={td}:offset={a_dur-td:.4f}[v01];"
            f"[v01][2:v]xfade=transition={trans_out}:duration={td}:offset={a_dur+b_dur-td*2:.4f}[vout]"
        ) if trans_in != "none" and trans_out != "none" else (
            f"[0:v][1:v][2:v]concat=n=3:v=1:a=0[vout]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", seg_a, "-i", seg_b, "-i", seg_c,
            "-filter_complex", filter_str,
            "-map", "[vout]", "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            out_preview,
        ]
        run_ffmpeg(cmd, label=f"Preview {i+1}: render con transición")
        preview_files.append(out_preview)

        insert_end = insert_at + clip_dur
        print(f"\nClip {i+1}: insert_at={insert_at}s → {insert_end:.1f}s "
              f"(transición: {trans_in}/{trans_out}, {td}s)")
        print(f"  Preview guardado en: {out_preview}")

    # Abrir todos los previews
    print("\nAbriendo previews...")
    for f in preview_files:
        subprocess.run(["open", f])

    print(f"\n{len(preview_files)} preview(s) generado(s). "
          "Verifica los timestamps y ajusta el TOML si es necesario.")


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def run(config_path: str, dry_run: bool = False, preview: bool = False):
    """
    Pipeline completo de post-procesamiento.
    1. Valida config
    2. (preview) Genera clips cortos para verificar timestamps
    3. (render)  Segmenta, aplica xfade, agrega end card, mux audio
    """
    print(f"\nCargando config: {config_path}")
    cfg = parse_config(config_path)

    base_video = cfg["base_video"]
    clips = cfg.get("clips", [])
    end_card = cfg.get("end_card")
    output = cfg["output"]

    print(f"  Video base:  {base_video}")
    print(f"  Output:      {output}")
    print(f"  Clips:       {len(clips)}")
    print(f"  End card:    {'si' if end_card else 'no'}")

    base_dur = get_video_duration(base_video)
    print(f"  Duración:    {base_dur:.1f}s")

    if preview:
        if not clips:
            print("\nNo hay clips definidos en el config para hacer preview.")
            return
        with tempfile.TemporaryDirectory(prefix="postprocess_preview_") as tmp:
            render_preview(base_video, clips, tmp)
        return

    # Modo render (o dry-run)
    with tempfile.TemporaryDirectory(prefix="postprocess_render_") as tmp:
        if dry_run:
            print("\n=== DRY RUN — solo se imprimen los comandos, no se ejecutan ===\n")

        if clips:
            video_composed = build_segment_commands(base_video, clips, tmp, dry_run)
        else:
            # Sin clips: copiar el video base tal cual al tmp para el siguiente paso
            video_composed = os.path.join(tmp, "video_composed.mp4")
            run_ffmpeg(
                ["ffmpeg", "-y", "-i", base_video, "-c:v", "copy", "-an", video_composed],
                dry_run=dry_run, label="Sin clips, extrayendo video"
            )

        if end_card:
            video_with_endcard = os.path.join(tmp, "video_with_endcard.mp4")
            apply_end_card(video_composed, end_card, video_with_endcard,
                           base_dur, dry_run)
            video_final_source = video_with_endcard
        else:
            video_final_source = video_composed

        # Reincorporar el audio original
        mux_audio(video_final_source, base_video, output, dry_run)

    if not dry_run:
        if os.path.exists(output):
            final_dur = get_video_duration(output)
            print(f"\n✓ Video final guardado en: {output} ({final_dur:.1f}s)")
        else:
            print("\n(dry-run: archivo no generado)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Post-procesa videos de MoneyPrinterTurbo: inserta screen recorders y agrega end card.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python postprocess/postprocess.py postprocess/configs/dreamiq_es.toml
  python postprocess/postprocess.py postprocess/configs/dreamiq_es.toml --preview
  python postprocess/postprocess.py postprocess/configs/dreamiq_es.toml --dry-run
        """,
    )
    parser.add_argument("config", help="Ruta al archivo .toml de configuración")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Imprime los comandos ffmpeg sin ejecutarlos"
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="Genera clips cortos alrededor de cada insertion point para verificar timestamps"
    )
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"ERROR: No se encontró el config: {args.config}")
        sys.exit(1)

    try:
        run(args.config, dry_run=args.dry_run, preview=args.preview)
    except (ValueError, RuntimeError) as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
