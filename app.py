import os
import io
import re
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = FastAPI(title="AURA BY MAY ROGA LLC - Asistente Consular", version="2.0")

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
    return re.sub(r'\s+', ' ', texto).strip().upper()

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
    
    if not p1 or not a1 or not datos.fecha_nacimiento or not lugar or not direccion or not telefono:
        raise HTTPException(status_code=400, detail="ALERTA: Faltan datos obligatorios. Verifique los campos antes de continuar.")
    
    if "-" not in datos.fecha_nacimiento:
        raise HTTPException(status_code=400, detail="Formato de fecha no válido.")
    
    ano, mes, dia = datos.fecha_nacimiento.split("-")
    fecha_formateada = f"{dia}/{mes}/{ano}"

    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    
    if datos.tipo_tramite == "pasaporte":
        nombre_base = "pasaporte"
        can.setFont("Helvetica-Bold", 13)
        can.drawString(40, 750, "GUÍA OFICIAL DE PREPARACIÓN CONSULAR: PASAPORTE MEXICANO")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(40, 725, "1. DATOS VERIFICADOS DEL SOLICITANTE:")
        can.setFont("Helvetica", 10)
        can.drawString(40, 710, f"Apellidos: {a1} {a2} | Nombres: {p1} {p2}")
        can.drawString(40, 695, f"Fecha de Nacimiento: {fecha_formateada} | Origen: {lugar}")
        can.drawString(40, 680, f"Domicilio USA (Con C.P.): {direccion} | Tel: {telefono}")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(40, 650, "CHECKLIST DE REQUISITOS OBLIGATORIOS (MARQUE CON UNA X):")
        can.setFont("Helvetica", 9)
        can.drawString(40, 635, "[  ] Acta de nacimiento mexicana original (Verificar que no sea extemporánea ni ilegible).")
        can.drawString(40, 620, "[  ] Identificación oficial vigente con fotografía (INE, Matrícula o Pasaporte anterior).")
        can.drawString(40, 605, "[  ] CURP certificada e impresa recientemente.")
        can.drawString(40, 590, "[  ] Comprobante de domicilio en EE. UU. con Código Postal visible.")
        can.setFont("Helvetica-Bold", 8)
        can.drawString(40, 570, "AVISO IMPORTANTE: Si el recibo está a nombre del propietario o rentador, lleve carta de residencia firmada.")

    elif datos.tipo_tramite == "matricula":
        nombre_base = "matricula"
        can.setFont("Helvetica-Bold", 13)
        can.drawString(40, 750, "GUÍA OFICIAL DE PREPARACIÓN CONSULAR: MATRÍCULA CONSULAR")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(40, 725, "1. DATOS VERIFICADOS DEL TITULAR:")
        can.setFont("Helvetica", 10)
        can.drawString(40, 710, f"Apellidos: {a1} {a2} | Nombres: {p1} {p2}")
        can.drawString(40, 695, f"Fecha de Nacimiento: {fecha_formateada} | Origen: {lugar}")
        can.drawString(40, 680, f"Domicilio USA (Con C.P.): {direccion} | Tel: {telefono}")
        can.drawString(40, 665, f"Emergencia: {ex1} | Tel: {ex2}")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(40, 640, "CHECKLIST DE REQUISITOS OBLIGATORIOS (MARQUE CON UNA X):")
        can.setFont("Helvetica", 9)
        can.drawString(40, 625, "[  ] Acta de nacimiento mexicana original.")
        can.drawString(40, 610, "[  ] Identificación oficial con fotografía vigente.")
        can.drawString(40, 595, "[  ] Comprobante de domicilio reciente en EE. UU. con Código Postal claro.")
        can.drawString(40, 580, "[  ] Datos de contacto de emergencia debidamente registrados.")
        can.setFont("Helvetica-Bold", 8)
        can.drawString(40, 560, "AVISO IMPORTANTE: Asegúrese de que su comprobante refleje exactamente la dirección actual.")

    elif datos.tipo_tramite == "registro":
        nombre_base = "registro_nacimiento"
        can.setFont("Helvetica-Bold", 13)
        can.drawString(40, 750, "GUÍA OFICIAL DE PREPARACIÓN: REGISTRO DE NACIMIENTO (DOBLE NACIONALIDAD)")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(40, 725, "1. DATOS VERIFICADOS DEL MENOR:")
        can.setFont("Helvetica", 10)
        can.drawString(40, 710, f"Apellidos: {a1} {a2} | Nombres: {p1} {p2}")
        can.drawString(40, 695, f"Fecha de Nacimiento: {fecha_formateada} | Lugar: {lugar}")
        can.drawString(40, 680, f"Padre/Madre Mexicano(a): {ex1}")
        can.drawString(40, 665, f"Hospital EE. UU.: {ex2}")
        can.setFont("Helvetica-Bold", 10)
        can.drawString(40, 640, "CHECKLIST DE REQUISITOS OBLIGATORIOS (MARQUE CON UNA X):")
        can.setFont("Helvetica", 9)
        can.drawString(40, 625, "[  ] Certificado de nacimiento de EE. UU. (Formato Largo / Long Form original).")
        can.drawString(40, 610, "[  ] Actas de nacimiento mexicanas originales de los padres.")
        can.drawString(40, 595, "[  ] Identificaciones oficiales vigentes de ambos padres.")
        can.drawString(40, 580, "[  ] Acta de matrimonio de los padres (si aplica) o presencia de ambos.")
        can.setFont("Helvetica-Bold", 8)
        can.drawString(40, 560, "AVISO IMPORTANTE: El certificado de EE. UU. debe ser el formato largo con firmas legibles.")

    else:
        raise HTTPException(status_code=400, detail="Trámite no válido.")

    # Escudo Legal de AURA BY MAY ROGA LLC en el PDF
    can.setFont("Helvetica-Oblique", 7)
    can.drawString(40, 50, "AURA BY MAY ROGA LLC | Servicio de Orientación Consular Profesional.")
    can.drawString(40, 40, "Esta guía es una herramienta de apoyo y no constituye un documento oficial de la SRE ni del gobierno.")
    can.drawString(40, 30, "La responsabilidad de presentar los documentos ante la autoridad consular recae exclusivamente en el usuario.")

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
        return FileResponse(ruta, media_type="application/pdf", filename="Guia_Oficial_Consular.pdf")
    raise HTTPException(status_code=404, detail="Archivo no encontrado.")

@app.get("/")
async def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Error: Falta index.html</h1>", status_code=500)
