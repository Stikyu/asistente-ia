"""
Asistente personal con IA (Claude) para tareas cotidianas.

Qué puede hacer:
  - Archivos: ver carpetas, buscar archivos, leer textos, crear carpetas, mover/renombrar
  - Tareas y notas: agregar, ver y completar tareas; guardar notas
  - Textos: redactar correos, resumir, traducir (y guardar borradores en Documentos)
  - Web: buscar información actual y leer páginas

Cómo usarlo:  python asistente.py   (o doble clic en iniciar.bat)
Para salir:   escribe "salir"
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from getpass import getpass
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
MODELO = "claude-opus-5-5"
CARPETA_DATOS = Path(__file__).parent / "datos"      # aquí se guardan tareas y notas
ARCHIVO_TAREAS = CARPETA_DATOS / "tareas.json"
ARCHIVO_NOTAS = CARPETA_DATOS / "notas.md"
CARPETA_PERMITIDA = Path.home()                      # el agente solo toca archivos dentro de tu carpeta de usuario
MAX_CARACTERES_LECTURA = 20000

INSTRUCCIONES = """Eres un asistente personal amable que ayuda con tareas cotidianas en una PC con Windows.
Responde siempre en español, de forma clara y breve.

Tienes herramientas para:
- Explorar y organizar archivos dentro de la carpeta del usuario (listar, buscar, leer, crear carpetas, mover/renombrar).
- Llevar una lista de tareas/recordatorios y guardar notas.
- Guardar borradores de texto (correos, resúmenes) como archivos .txt.
- Buscar en internet y leer páginas web.
- Consultar la fecha y hora actual (úsala cuando el usuario mencione "hoy", "mañana", fechas límite, etc.).

Reglas:
- Antes de reorganizar muchos archivos, explica brevemente qué piensas hacer.
- Nunca inventes contenido de archivos: léelos con la herramienta.
- Cuando busques en la web, menciona de dónde sacaste la información.
- Si el usuario pide redactar un correo, muéstralo en la respuesta y ofrece guardarlo como borrador."""


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def ruta_segura(ruta: str) -> Path:
    """Convierte el texto en una ruta y verifica que esté dentro de la carpeta permitida."""
    p = Path(os.path.expandvars(os.path.expanduser(ruta)))
    if not p.is_absolute():
        p = CARPETA_PERMITIDA / p
    p = p.resolve()
    if not p.is_relative_to(CARPETA_PERMITIDA.resolve()):
        raise PermissionError(f"Solo puedo acceder a archivos dentro de {CARPETA_PERMITIDA}")
    return p


def confirmar(pregunta: str) -> bool:
    respuesta = input(f"\n  ⚠️  {pregunta} (s/n): ").strip().lower()
    return respuesta in ("s", "si", "sí", "y", "yes")


def cargar_tareas() -> list:
    if ARCHIVO_TAREAS.exists():
        return json.loads(ARCHIVO_TAREAS.read_text(encoding="utf-8"))
    return []


def guardar_tareas(tareas: list) -> None:
    CARPETA_DATOS.mkdir(exist_ok=True)
    ARCHIVO_TAREAS.write_text(json.dumps(tareas, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Herramientas (lo que el agente puede hacer en tu PC)
# ---------------------------------------------------------------------------
def obtener_fecha_hora() -> str:
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    ahora = datetime.now()
    return f"{dias[ahora.weekday()]} {ahora.strftime('%Y-%m-%d %H:%M')}"


def listar_carpeta(ruta: str) -> str:
    carpeta = ruta_segura(ruta)
    if not carpeta.is_dir():
        return f"No existe la carpeta: {carpeta}"
    lineas = []
    for item in sorted(carpeta.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:300]:
        if item.is_dir():
            lineas.append(f"[carpeta] {item.name}")
        else:
            try:
                st = item.stat()
                fecha = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")
                lineas.append(f"{item.name}  ({st.st_size / 1024:.0f} KB, modificado {fecha})")
            except OSError:
                lineas.append(item.name)
    return f"Contenido de {carpeta}:\n" + ("\n".join(lineas) or "(vacía)")


def buscar_archivos(carpeta: str, patron: str) -> str:
    base = ruta_segura(carpeta)
    resultados = []
    for p in base.rglob(patron):
        resultados.append(str(p))
        if len(resultados) >= 100:
            resultados.append("... (hay más resultados, se muestran los primeros 100)")
            break
    return "\n".join(resultados) or "No se encontraron archivos."


def leer_archivo(ruta: str) -> str:
    archivo = ruta_segura(ruta)
    if not archivo.is_file():
        return f"No existe el archivo: {archivo}"
    texto = archivo.read_text(encoding="utf-8", errors="replace")
    if len(texto) > MAX_CARACTERES_LECTURA:
        return texto[:MAX_CARACTERES_LECTURA] + f"\n\n[... archivo recortado: muestra {MAX_CARACTERES_LECTURA} de {len(texto)} caracteres]"
    return texto


def crear_carpeta(ruta: str) -> str:
    carpeta = ruta_segura(ruta)
    carpeta.mkdir(parents=True, exist_ok=True)
    return f"Carpeta lista: {carpeta}"


def mover_archivo(origen: str, destino: str) -> str:
    o, d = ruta_segura(origen), ruta_segura(destino)
    if not o.exists():
        return f"No existe: {o}"
    if d.is_dir():
        d = d / o.name
    if d.exists():
        return f"Ya existe un archivo en {d}; no lo sobrescribo."
    if not confirmar(f"¿Mover/renombrar\n      {o}\n   →  {d}?"):
        return "El usuario NO autorizó esta acción."
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(o), str(d))
    return f"Movido: {o} → {d}"


def agregar_tarea(descripcion: str, fecha_limite: str = "") -> str:
    tareas = cargar_tareas()
    nuevo_id = max((t["id"] for t in tareas), default=0) + 1
    tareas.append({"id": nuevo_id, "descripcion": descripcion, "fecha_limite": fecha_limite,
                   "hecha": False, "creada": datetime.now().strftime("%Y-%m-%d %H:%M")})
    guardar_tareas(tareas)
    return f"Tarea #{nuevo_id} agregada."


def listar_tareas(incluir_hechas: bool = False) -> str:
    tareas = [t for t in cargar_tareas() if incluir_hechas or not t["hecha"]]
    if not tareas:
        return "No hay tareas."
    return "\n".join(
        f"#{t['id']} [{'x' if t['hecha'] else ' '}] {t['descripcion']}"
        + (f" (para: {t['fecha_limite']})" if t["fecha_limite"] else "")
        for t in tareas
    )


def completar_tarea(id: int) -> str:
    tareas = cargar_tareas()
    for t in tareas:
        if t["id"] == id:
            t["hecha"] = True
            guardar_tareas(tareas)
            return f"Tarea #{id} marcada como hecha."
    return f"No encontré la tarea #{id}."


def guardar_nota(texto: str) -> str:
    CARPETA_DATOS.mkdir(exist_ok=True)
    with ARCHIVO_NOTAS.open("a", encoding="utf-8") as f:
        f.write(f"\n## {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{texto}\n")
    return f"Nota guardada en {ARCHIVO_NOTAS}"


def leer_notas() -> str:
    return ARCHIVO_NOTAS.read_text(encoding="utf-8") if ARCHIVO_NOTAS.exists() else "No hay notas todavía."


def guardar_borrador(nombre_archivo: str, contenido: str) -> str:
    carpeta = Path.home() / "Documents" / "Borradores asistente"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = "".join(c for c in nombre_archivo if c not in '<>:"/\\|?*').strip() or "borrador"
    if not nombre.endswith(".txt"):
        nombre += ".txt"
    destino = carpeta / nombre
    destino.write_text(contenido, encoding="utf-8")
    return f"Borrador guardado en {destino}"


# Relación nombre -> función
FUNCIONES = {f.__name__: f for f in [
    obtener_fecha_hora, listar_carpeta, buscar_archivos, leer_archivo, crear_carpeta, mover_archivo,
    agregar_tarea, listar_tareas, completar_tarea, guardar_nota, leer_notas, guardar_borrador,
]}


def herramienta(nombre, descripcion, propiedades=None, requeridos=None):
    return {
        "name": nombre,
        "description": descripcion,
        "input_schema": {"type": "object", "properties": propiedades or {}, "required": requeridos or []},
    }


TEXTO = {"type": "string"}
HERRAMIENTAS = [
    herramienta("obtener_fecha_hora", "Devuelve el día de la semana, la fecha y la hora actuales."),
    herramienta("listar_carpeta",
                "Lista archivos y subcarpetas de una carpeta. Acepta rutas como '~/Downloads' o 'C:/Users/...'.",
                {"ruta": TEXTO}, ["ruta"]),
    herramienta("buscar_archivos",
                "Busca archivos recursivamente dentro de una carpeta usando un patrón tipo '*.pdf' o '*factura*'.",
                {"carpeta": TEXTO, "patron": TEXTO}, ["carpeta", "patron"]),
    herramienta("leer_archivo", "Lee el contenido de un archivo de texto (txt, md, csv, código, etc.).",
                {"ruta": TEXTO}, ["ruta"]),
    herramienta("crear_carpeta", "Crea una carpeta (y las intermedias si no existen).", {"ruta": TEXTO}, ["ruta"]),
    herramienta("mover_archivo",
                "Mueve o renombra un archivo o carpeta. Si el destino es una carpeta existente, lo mete dentro. "
                "El usuario debe confirmar cada movimiento.",
                {"origen": TEXTO, "destino": TEXTO}, ["origen", "destino"]),
    herramienta("agregar_tarea", "Agrega una tarea o recordatorio a la lista del usuario.",
                {"descripcion": TEXTO,
                 "fecha_limite": {"type": "string", "description": "Fecha en formato AAAA-MM-DD (opcional)"}},
                ["descripcion"]),
    herramienta("listar_tareas", "Muestra la lista de tareas pendientes.",
                {"incluir_hechas": {"type": "boolean", "description": "true para incluir también las completadas"}}),
    herramienta("completar_tarea", "Marca una tarea como hecha usando su número.",
                {"id": {"type": "integer"}}, ["id"]),
    herramienta("guardar_nota", "Guarda una nota de texto con fecha.", {"texto": TEXTO}, ["texto"]),
    herramienta("leer_notas", "Lee todas las notas guardadas."),
    herramienta("guardar_borrador",
                "Guarda un texto (por ejemplo un correo redactado) como archivo .txt en Documentos/Borradores asistente.",
                {"nombre_archivo": TEXTO, "contenido": TEXTO}, ["nombre_archivo", "contenido"]),
    # Herramientas de internet (se ejecutan en los servidores de Anthropic)
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5},
]


def ejecutar_herramienta(nombre: str, entrada: dict) -> tuple[str, bool]:
    """Ejecuta una herramienta local. Devuelve (resultado, hubo_error)."""
    print(f"  🔧 {nombre}({', '.join(f'{k}={v!r}' for k, v in entrada.items())[:150]})")
    try:
        return str(FUNCIONES[nombre](**entrada)), False
    except Exception as e:  # el error se le devuelve al modelo para que lo explique o lo intente de otra forma
        return f"Error: {e}", True


# ---------------------------------------------------------------------------
# Bucle del agente
# ---------------------------------------------------------------------------
def responder(client: anthropic.Anthropic, mensajes: list) -> None:
    """Llama a Claude, ejecuta las herramientas que pida y repite hasta tener la respuesta final."""
    inicio_turno = len(mensajes) - 1  # para deshacer el turno si algo sale mal
    while True:
        respuesta = client.beta.messages.create(
            model=MODELO,
            max_tokens=16000,
            system=INSTRUCCIONES,
            tools=HERRAMIENTAS,
            messages=mensajes,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            cache_control={"type": "ephemeral"},      # abarata la conversación reutilizando lo ya enviado
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                       # si el modelo rechaza algo, reintenta con otro modelo
        )

        if respuesta.stop_reason == "refusal":
            print("\nAsistente: Lo siento, no puedo ayudar con esa solicitud.\n")
            del mensajes[inicio_turno:]
            return

        mensajes.append({"role": "assistant", "content": respuesta.content})

        for bloque in respuesta.content:
            if bloque.type == "text" and bloque.text.strip():
                print(f"\nAsistente: {bloque.text}\n")
            elif bloque.type == "server_tool_use":
                print(f"  🌐 {bloque.name}: {json.dumps(bloque.input, ensure_ascii=False)[:120]}")

        if respuesta.stop_reason == "pause_turn":   # una búsqueda web larga: se continúa
            continue

        if respuesta.stop_reason == "tool_use":
            resultados = []
            for bloque in respuesta.content:
                if bloque.type == "tool_use":
                    resultado, error = ejecutar_herramienta(bloque.name, bloque.input)
                    resultados.append({"type": "tool_result", "tool_use_id": bloque.id,
                                       "content": resultado, "is_error": error})
            mensajes.append({"role": "user", "content": resultados})
            continue

        if respuesta.stop_reason == "max_tokens":
            print("  (La respuesta se cortó por ser demasiado larga. Pide que continúe.)\n")
        return


def obtener_cliente() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Necesito tu clave de API de Anthropic.")
        print("Créala en https://console.anthropic.com/settings/keys y pégala aquí (no se verá al escribir).")
        clave = getpass("Clave: ").strip()
        if not clave:
            sys.exit("No se ingresó ninguna clave.")
        os.environ["ANTHROPIC_API_KEY"] = clave
        if confirmar("¿Guardar la clave en tu usuario de Windows para no volver a pedirla?"):
            subprocess.run(["setx", "ANTHROPIC_API_KEY", clave], capture_output=True)
            print("  Guardada. (Se usará automáticamente la próxima vez.)")
    return anthropic.Anthropic()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    client = obtener_cliente()
    mensajes: list = []

    print("=" * 60)
    print("  🤖 Asistente personal — escribe lo que necesitas")
    print("  Ejemplos: 'organiza mi carpeta de Descargas por tipo'")
    print("            'recuérdame pagar la luz el viernes'")
    print("            'redacta un correo pidiendo un día libre'")
    print("            '¿qué clima hará mañana en Bogotá?'")
    print("  Escribe 'salir' para terminar, 'nuevo' para empezar otra conversación.")
    print("=" * 60)

    while True:
        try:
            texto = input("\nTú: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not texto:
            continue
        if texto.lower() in ("salir", "exit", "adios", "adiós"):
            break
        if texto.lower() == "nuevo":
            mensajes = []
            print("  (Conversación reiniciada)")
            continue

        mensajes.append({"role": "user", "content": texto})
        try:
            responder(client, mensajes)
        except anthropic.AuthenticationError:
            print("\n❌ La clave de API no es válida. Revisa ANTHROPIC_API_KEY.")
            break
        except anthropic.RateLimitError:
            print("\n⏳ Demasiadas solicitudes seguidas. Espera un momento y vuelve a intentar.")
            mensajes.clear()
        except anthropic.APIConnectionError:
            print("\n🌐 No hay conexión con el servidor. Revisa tu internet.")
            mensajes.clear()
        except anthropic.APIStatusError as e:
            print(f"\n❌ Error del servidor ({e.status_code}): {e.message}")
            mensajes.clear()

    print("\n¡Hasta luego! 👋")


if __name__ == "__main__":
    main()
