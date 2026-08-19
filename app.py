import os
import io
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = FastAPI(title="Asistente Consular Mexicano", version="1.1")

# Directorios de trabajo
PLANTILLAS_DIR = "plantillas"
SALIDAS_DIR = "salidas"

os.makedirs(PLANTILLAS_DIR, exist_ok=True)
os.makedirs(SALIDAS_DIR, exist_ok=True)

class DatosMexicano(BaseModel):
    tipo_tramite: str  # "pasaporte" o "matricula"
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

    # Definir el título según el trámite seleccionado
    if datos.tipo_tramite == "pasaporte":
        titulo_doc = "FORMATO DE SOLICITUD DE PASAPORTE MEXICANO"
        nombre_base = "pasaporte"
    elif datos.tipo_tramite == "matricula":
        titulo_doc = "FORMATO DE SOLICITUD DE MATRÍCULA CONSULAR"
        nombre_base = "matricula"
    else:
        raise HTTPException(status_code=400, detail="Tipo de trámite no válido.")

    nombre_salida = f"{nombre_base}_mexicano_{os.urandom(4).hex()}.pdf"
    ruta_salida = os.path.join(SALIDAS_DIR, nombre_salida)

    # Generar la capa visual con los datos del solicitante
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    can.setFont("Helvetica-Bold", 14)
    can.drawString(50, 740, titulo_doc)
    
    can.setFont("Helvetica-Bold", 11)
    can.drawString(50, 700, "DATOS PERSONALES:")
    can.setFont("Helvetica", 11)
    can.drawString(50, 680, f"Apellido Paterno: {a1}")
    can.drawString(300, 680, f"Apellido Materno: {a2}")
    can.drawString(50, 650, f"Primer Nombre: {p1}")
    can.drawString(300, 650, f"Segundo Nombre: {p2}")
    
    can.setFont("Helvetica-Bold", 11)
    can.drawString(50, 610, "NACIMIENTO Y ORIGEN:")
    can.setFont("Helvetica", 11)
    can.drawString(50, 590, f"Fecha de Nacimiento: {fecha_formateada}")
    can.drawString(300, 590, f"Estado en México: {limpiar_texto(datos.lugar_nacimiento)}")
    
    can.setFont("Helvetica-Bold", 11)
    can.drawString(50, 550, "CONTACTO Y UBICACIÓN EN ESTADOS UNIDOS:")
    can.setFont("Helvetica", 11)
    can.drawString(50, 530, f"Dirección actual: {limpiar_texto(datos.direccion_usa)}")
    can.drawString(50, 500, f"Teléfono: {limpiar_texto(datos.telefono)}")
    
    can.save()
    packet.seek(0)
    
    # Crear y guardar el PDF final
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
    return HTMLResponse(content="<h1>Error: Falta el archivo index.html en el servidor</h1>", status_code=500)
