import os
import io
import re
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

app = FastAPI(title="AURA BY MAY ROGA LLC - Asistente Consular", version="2.1")

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

    # Configuración del PDF con ReportLab Flowables para máxima elegancia y cero amontonamiento
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    # Estilos profesionales personalizados
    estilo_titulo = ParagraphStyle(
        'TituloDoc',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#b32134"),
        alignment=1, # Centrado
        spaceAfter=15
    )
    
    estilo_seccion = ParagraphStyle(
        'SeccionDoc',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#1a1a1a"),
        spaceBefore=12,
        spaceAfter=6
    )
    
    estilo_texto = ParagraphStyle(
        'TextoDoc',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#333333"),
        spaceAfter=4
    )
    
    estilo_aviso = ParagraphStyle(
        'AvisoDoc',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#856404"),
        spaceBefore=6,
        spaceAfter=6
    )

    estilo_legal = ParagraphStyle(
        'LegalDoc',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#666666"),
        alignment=1,
        spaceBefore=20
    )

    elementos = []

    # Encabezado institucional
    elementos.append(Paragraph("AURA BY MAY ROGA LLC", estilo_titulo))
    
    if datos.tipo_tramite == "pasaporte":
        nombre_base = "pasaporte"
        titulo_tramite = "GUÍA OFICIAL DE PREPARACIÓN CONSULAR: PASAPORTE MEXICANO"
        requisitos = [
            "Acta de nacimiento mexicana original (Verificar que no sea extemporánea ni ilegible).",
            "Identificación oficial vigente con fotografía (INE, Matrícula o Pasaporte anterior).",
            "CURP certificada e impresa recientemente.",
            "Comprobante de domicilio en EE. UU. con Código Postal visible."
        ]
        nota_importante = "AVISO IMPORTANTE: Si el recibo de domicilio está a nombre del propietario o rentador, lleve una carta de residencia firmada."
    elif datos.tipo_tramite == "matricula":
        nombre_base = "matricula"
        titulo_tramite = "GUÍA OFICIAL DE PREPARACIÓN CONSULAR: MATRÍCULA CONSULAR"
        requisitos = [
            "Acta de nacimiento mexicana original.",
            "Identificación oficial con fotografía vigente.",
            "Comprobante de domicilio reciente en EE. UU. con Código Postal claro.",
            "Datos de contacto de emergencia debidamente registrados."
        ]
        nota_importante = "AVISO IMPORTANTE: Asegúrese de que su comprobante refleje exactamente su dirección residencial actual."
    elif datos.tipo_tramite == "registro":
        nombre_base = "registro_nacimiento"
        titulo_tramite = "GUÍA OFICIAL DE PREPARACIÓN: REGISTRO DE NACIMIENTO (DOBLE NACIONALIDAD)"
        requisitos = [
            "Certificado de nacimiento de EE. UU. (Formato Largo / Long Form original).",
            "Actas de nacimiento mexicanas originales de los padres.",
            "Identificaciones oficiales vigentes de ambos padres.",
            "Acta de matrimonio de los padres (si aplica) o presencia de ambos."
        ]
        nota_importante = "AVISO IMPORTANTE: El certificado de EE. UU. debe ser el formato largo con firmas legibles."
    else:
        raise HTTPException(status_code=400, detail="Trámite no válido.")

    elementos.append(Paragraph(titulo_tramite, estilo_seccion))
    elementos.append(Spacer(1, 5))

    # Tabla de datos limpios y profesionales
    if datos.tipo_tramite == "pasaporte":
        datos_tabla = [
            [Paragraph("<b>Titular:</b>", estilo_texto), Paragraph(f"{p1} {p2} {a1} {a2}", estilo_texto)],
            [Paragraph("<b>Nacimiento:</b>", estilo_texto), Paragraph(f"{fecha_formateada} ({lugar})", estilo_texto)],
            [Paragraph("<b>Domicilio USA:</b>", estilo_texto), Paragraph(f"{direccion}", estilo_texto)],
            [Paragraph("<b>Teléfono:</b>", estilo_texto), Paragraph(f"{telefono}", estilo_texto)]
        ]
    elif datos.tipo_tramite == "matricula":
        datos_tabla = [
            [Paragraph("<b>Titular:</b>", estilo_texto), Paragraph(f"{p1} {p2} {a1} {a2}", estilo_texto)],
            [Paragraph("<b>Nacimiento:</b>", estilo_texto), Paragraph(f"{fecha_formateada} ({lugar})", estilo_texto)],
            [Paragraph("<b>Domicilio USA:</b>", estilo_texto), Paragraph(f"{direccion} | Tel: {telefono}", estilo_texto)],
            [Paragraph("<b>Emergencia:</b>", estilo_texto), Paragraph(f"{ex1} (Tel: {ex2})", estilo_texto)]
        ]
    else:
        datos_tabla = [
            [Paragraph("<b>Menor:</b>", estilo_texto), Paragraph(f"{p1} {p2} {a1} {a2}", estilo_texto)],
            [Paragraph("<b>Nacimiento:</b>", estilo_texto), Paragraph(f"{fecha_formateada} en {lugar}", estilo_texto)],
            [Paragraph("<b>Familiar:</b>", estilo_texto), Paragraph(f"Padre/Madre: {ex1}", estilo_texto)],
            [Paragraph("<b>Hospital USA:</b>", estilo_texto), Paragraph(f"{ex2}", estilo_texto)]
        ]

    t = Table(datos_tabla, colWidths=[110, 420])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8f9fa")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#d6d8db")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e9ecef")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    
    elementos.append(t)
    elementos.append(Spacer(1, 15))

    # Sección de Checklist con diseño limpio
    elementos.append(Paragraph("CHECKLIST DE REQUISITOS OBLIGATORIOS", estilo_seccion))
    
    checklist_data = []
    for req in requisitos:
        checklist_data.append([Paragraph("[   ]", estilo_texto), Paragraph(req, estilo_texto)])

    t_check = Table(checklist_data, colWidths=[30, 500])
    t_check.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    
    elementos.append(t_check)
    elementos.append(Spacer(1, 10))
    elementos.append(Paragraph(nota_importante, estilo_aviso))
    elementos.append(Spacer(1, 20))

    # Escudo Legal de AURA BY MAY ROGA LLC
    texto_legal = (
        "AURA BY MAY ROGA LLC | Servicio de Orientación Consular Profesional.<br/>"
        "Esta guía es una herramienta de apoyo administrativo independiente y no constituye un documento oficial gubernamental.<br/>"
        "La responsabilidad de presentar correctamente los documentos ante la autoridad consular recae exclusivamente en el usuario."
    )
    elementos.append(Paragraph(texto_legal, estilo_legal))

    doc.build(elementos)
    buffer.seek(0)
    
    nombre_salida = f"{nombre_base}_mexicano_{os.urandom(4).hex()}.pdf"
    ruta_salida = os.path.join(SALIDAS_DIR, nombre_salida)
    
    with open(ruta_salida, "wb") as f:
        f.write(buffer.getvalue())

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
