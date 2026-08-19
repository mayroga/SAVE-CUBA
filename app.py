import os
import io
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = FastAPI(title="Asistente Consular Mexicano", version="1.0")

# Directorios de trabajo
PLANTILLAS_DIR = "plantillas"
SALIDAS_DIR = "salidas"

os.makedirs(PLANTILLAS_DIR, exist_ok=True)
os.makedirs(SALIDAS_DIR, exist_ok=True)

class DatosMexicano(BaseModel):
    primer_nombre: str
    segundo_nombre: str = ""
    primer_apellido: str
    segundo_apellido: str = ""
    fecha_nacimiento: str  # Formato YYYY-MM-DD
    lugar_nacimiento: str  # Estado de México
    direccion_usa: str
    telefono: str

def limpiar_texto(texto: str) -> str:
    if not texto:
        return ""
    return texto.strip().upper()

@app.post("/api/generar-tramite-mexicano")
async def generar_tramite(datos: DatosMexicano):
    p1 = limpiar_texto(datos.primer_nombre)
    p2 = limpiar_texto(datos.segundo_nombre)
    a1 = limpiar_texto(datos.primer_apellido)
    a2 = limpiar_texto(datos.segundo_apellido)
    
    if not p1 or not a1:
        raise HTTPException(status_code=400, detail="El primer nombre y el primer apellido son obligatorios.")
    
    if not datos.fecha_nacimiento or "-" not in datos.fecha_nacimiento:
        raise HTTPException(status_code=400, detail="Fecha de nacimiento inválida.")
    
    ano, mes, dia = datos.fecha_nacimiento.split("-")
    fecha_formateada = f"{dia}/{mes}/{ano}"

    nombre_salida = f"pasaporte_mexicano_{os.urandom(4).hex()}.pdf"
    ruta_salida = os.path.join(SALIDAS_DIR, nombre_salida)
    ruta_plantilla = os.path.join(PLANTILLAS_DIR, "pasaporte_mexicano.pdf")

    # Si no existe la plantilla física en el servidor, generamos una base limpia profesional con ReportLab
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    can.setFont("Helvetica-Bold", 12)
    
    # Estampado en coordenadas exactas de la planilla consular
    can.drawString(100, 720, f"APELLIDO PATERNO: {a1}")
    can.drawString(320, 720, f"APELLIDO MATERNO: {a2}")
    can.drawString(100, 680, f"NOMBRE(S): {p1} {p2}")
    can.drawString(100, 640, f"FECHA DE NACIMIENTO: {fecha_formateada}")
    can.drawString(320, 640, f"LUGAR DE NACIMIENTO: {limpiar_texto(datos.lugar_nacimiento)}")
    can.drawString(100, 600, f"DIRECCION EN USA: {limpiar_texto(datos.direccion_usa)}")
    can.drawString(100, 560, f"TELEFONO: {limpiar_texto(datos.telefono)}")
    
    can.save()
    packet.seek(0)
    
    # Guardar PDF final listo para descargar o imprimir
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
        return FileResponse(ruta, media_type="application/pdf", filename="Formato_Consular_Mexicano.pdf")
    raise HTTPException(status_code=404, detail="Archivo no encontrado.")

@app.get("/")
async def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())
