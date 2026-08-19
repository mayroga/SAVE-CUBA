import os
import io
import re
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = FastAPI(title="Asistente Consular Inteligente", version="1.4")

PLANTILLAS_DIR = "plantillas"
SALIDAS_DIR = "salidas"

os.makedirs(PLANTILLAS_DIR, exist_ok=True)
os.makedirs(SALIDAS_DIR, exist_ok=True)

class DatosMexicano(BaseModel):
    tipo_tramite: str
    primer_nombre: str
    segundo_nombre: str = ""
    primer_apellido: str
    segundo_apellido: str = ""
    fecha_nacimiento: str
    lugar_nacimiento: str
    direccion_usa: str
    telefono: str
    extra_1: str = ""
    extra_2: str = ""

def limpiar_y_corregir(texto: str) -> str:
    if not texto:
        return ""
    # Eliminar espacios múltiples y caracteres extraños ilegales, manteniendo acentos y letras limpias
    texto_limpio = re.sub(r'\s+', ' ', texto).strip()
    # Convertir a mayúsculas de manera inteligente
    return texto_limpio.upper()

@app.post("/api/generar-tramite-mexicano")
async def generar_tramite(datos: DatosMexicano):
    p1 = limpiar_y_corregir(datos.primer_nombre)
    p2 = limpiar_y_corregir(datos.segundo_nombre)
    a1 = limpiar_y_corregir(datos.primer_apellido)
    a2 = limpiar_y_corregir(datos.segundo_apellido)
    lugar = limpiar_y_corregir(datos.lugar_nacimiento)
    direccion = limpiar_y_corregir(datos.direccion_usa)
    telefono = limpiar_y_corregir(datos.telefono)
    ex1 = limpiar_y_corregir(datos.extra_1)
    ex2 = limpiar_y_corregir(datos.extra_2)
    
    # Validación estricta anti casillas en blanco
    if not p1 or not a1 or not datos.fecha_nacimiento or not lugar or not direccion or not telefono:
        raise HTTPException(status_code=400, detail="ALERTA: Hay campos obligatorios en blanco. Ningún dato puede quedar vacío.")
    
    if "-" not in datos.fecha_nacimiento:
        raise HTTPException(status_code=400, detail="Fecha de nacimiento inválida.")
    
    ano, mes, dia = datos.fecha_nacimiento.split("-")
    fecha_formateada = f"{dia}/{mes}/{ano}"

    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    
    if datos.tipo_tramite == "pasaporte":
        nombre_base = "pasaporte"
        can.setFont("Helvetica-Bold", 13)
        can.drawString(50, 750, "SOLICITUD DE PASAPORTE ORDINARIO MEXICANO")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(50, 720, "1. DATOS VERIFICADOS DEL SOLICITANTE:")
        can.setFont("Helvetica", 10)
        can.drawString(50, 705, f"Apellidos: {a1} {a2} | Nombres: {p1} {p2}")
        can.drawString(50, 690, f"Nacimiento: {fecha_formateada} | Estado: {lugar}")
        can.drawString(50, 675, f"Domicilio USA: {direccion} | Tel: {telefono}")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(50, 645, "REQUISITOS OBLIGATORIOS QUE DEBE LLEVAR AL CONSULADO:")
        can.setFont("Helvetica", 9)
        can.drawString(50, 630, "- Acta de nacimiento mexicana original y legible (sin tachaduras).")
        can.drawString(50, 615, "- Identificación oficial vigente con fotografía (INE, Matrícula o Pasaporte anterior).")
        can.drawString(50, 600, "- CURP certificado e impreso recientemente.")
        can.drawString(50, 585, "- Comprobante de pago de derechos consulares.")

    elif datos.tipo_tramite == "matricula":
        nombre_base = "matricula"
        can.setFont("Helvetica-Bold", 13)
        can.drawString(50, 750, "SOLICITUD DE MATRÍCULA CONSULAR DE ALTA SEGURIDAD")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(50, 720, "1. DATOS VERIFICADOS DE IDENTIDAD:")
        can.setFont("Helvetica", 10)
        can.drawString(50, 705, f"Apellidos: {a1} {a2} | Nombres: {p1} {p2}")
        can.drawString(50, 690, f"Fecha de Nacimiento: {fecha_formateada} | Origen: {lugar}")
        can.drawString(50, 675, f"Domicilio USA: {direccion} | Tel: {telefono}")
        can.drawString(50, 660, f"Contacto de Emergencia: {ex1} (Tel: {ex2})")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(50, 630, "REQUISITOS OBLIGATORIOS QUE DEBE LLEVAR AL CONSULADO:")
        can.setFont("Helvetica", 9)
        can.drawString(50, 615, "- Acta de nacimiento mexicana original.")
        can.drawString(50, 600, "- Comprobante de domicilio reciente en EE. UU.")
        can.drawString(50, 585, "- Identificación oficial con fotografía vigente.")

    elif datos.tipo_tramite == "registro":
        nombre_base = "registro_nacimiento"
        can.setFont("Helvetica-Bold", 13)
        can.drawString(50, 750, "SOLICITUD DE REGISTRO DE NACIMIENTO (DOBLE NACIONALIDAD)")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(50, 720, "1. DATOS VERIFICADOS DEL MENOR REGISTRADO:")
        can.setFont("Helvetica", 10)
        can.drawString(50, 705, f"Apellidos: {a1} {a2} | Nombres: {p1} {p2}")
        can.drawString(50, 690, f"Fecha de Nacimiento: {fecha_formateada} | Hospital/Lugar: {lugar}")
        can.drawString(50, 675, f"Padre/Madre Mexicano(a): {ex1}")
        can.drawString(50, 660, f"Hospital de EE. UU.: {ex2}")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(50, 630, "REQUISITOS OBLIGATORIOS QUE DEBE LLEVAR AL CONSULADO:")
        can.setFont("Helvetica", 9)
        can.drawString(50, 615, "- Certificado de nacimiento de EE. UU. (Formato Largo / Apostillado).")
        can.drawString(50, 600, "- Acta de nacimiento mexicana de los padres (originales).")
        can.drawString(50, 585, "- Identificación oficial vigente de ambos padres.")

    can.save()
    packet.seek(0)
    
    nombre_salida = f"{nombre_base}_mexicano_{os.urandom(4).hex()}.pdf"
    ruta_salida = os.path.join(SALIDAS_DIR, nombre_salida)
    
    new_pdf = PdfReader(packet)
    writer = PdfWriter()
    writer.add_page(new_pdf.pages[0])
    
    with open(ruta_salida, "wb") as f:
        writer.write(f)

    return {"status": "success", "archivo": f"/descargar/{nombre_salida}"}

@app.get("/descargar/{nombre_archivo}")
async def descargar(nombre_archivo: str):
    ruta = os.path.join(SALIDAS_DIR, nombre_archivo)
    if os.path.exists(ruta):
        return FileResponse(ruta, media_type="application/pdf", filename="Documento_Consular_Oficial.pdf")
    raise HTTPException(status_code=404, detail="Archivo no encontrado.")

@app.get("/")
async def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Error: Falta el archivo index.html</h1>", status_code=500)
