import os
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

# Configuración de rutas y logging
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLAS_DIR = os.path.join(BASE_DIR, "plantillas")
SALIDAS_DIR = os.path.join(BASE_DIR, "salidas")
os.makedirs(SALIDAS_DIR, exist_ok=True)

app = FastAPI()

# Definición del modelo de datos para SAVE CUBA
class DatosClienteUnificados(BaseModel):
    primer_nombre: str
    segundo_nombre: Optional[str] = ""
    primer_apellido: str
    segundo_apellido: Optional[str] = ""
    fecha_nacimiento: str
    anumber: Optional[str] = ""
    pasaporte_actual: Optional[str] = ""
    provincia_cuba: Optional[str] = ""
    ano_salida_cuba: Optional[str] = ""
    empleo_cuba_espanol: Optional[str] = ""
    tramite_tipo: str

# Funciones de saneamiento y validación
def corregir_y_sanear_texto(texto: str, es_obligatorio: bool = False, nombre_campo: str = "") -> str:
    if es_obligatorio and (not texto or texto.strip() == ""):
        raise HTTPException(status_code=400, detail=f"El campo {nombre_campo} es obligatorio.")
    return texto.strip() if texto else ""

def validar_y_limpiar_anumber(anumber: str, es_obligatorio: bool = False) -> str:
    if es_obligatorio and (not anumber or len(anumber) < 7):
        raise HTTPException(status_code=400, detail="A-Number inválido o incompleto.")
    return anumber.strip()

def validar_y_limpiar_pasaporte(pasaporte: str, es_obligatorio: bool = False) -> str:
    if es_obligatorio and (not pasaporte or len(pasaporte) < 5):
        raise HTTPException(status_code=400, detail="Número de pasaporte inválido.")
    return pasaporte.strip()

def traducir_historial_laboral_ia(texto: str) -> str:
    # Lógica de procesamiento de texto sin menciones prohibidas
    return texto.upper() if texto else "N/A"

# Motor de inyección de datos en PDF
def rellenar_planilla_pdf(nombre_archivo: str, datos: dict, nombre_salida: str):
    ruta_origen = os.path.join(PLANTILLAS_DIR, nombre_archivo)
    ruta_destino = os.path.join(SALIDAS_DIR, nombre_salida)
    
    reader = PdfReader(ruta_origen)
    writer = PdfWriter()
    
    for page in reader.pages:
        writer.add_page(page)
        
    writer.update_page_form_field_values(writer.pages[0], datos)
    
    with open(ruta_destino, "wb") as f:
        writer.write(f)
# =====================================================================
# MOTOR SEPARADOR Y EJECUTOR DE TRÁMITES (AUTOLLENADO COMPLETO Y REAL)
# =====================================================================
def ejecutar_mapeo_y_guardado(cliente: DatosClienteUnificados, id_archivo_salida: str):
    nombre1 = corregir_y_sanear_texto(cliente.primer_nombre, es_obligatorio=True, nombre_campo="Primer Nombre")
    nombre2 = corregir_y_sanear_texto(cliente.segundo_nombre)
    apellido1 = corregir_y_sanear_texto(cliente.primer_apellido, es_obligatorio=True, nombre_campo="Primer Apellido")
    apellido2 = corregir_y_sanear_texto(cliente.segundo_apellido)
    
    if not cliente.fecha_nacimiento or "-" not in cliente.fecha_nacimiento:
        raise HTTPException(status_code=400, detail="¡Atención! La Fecha de Nacimiento es inválida o está vacía.")
    
    ano, mes, dia = cliente.fecha_nacimiento.split("-")
    fecha_usa = f"{mes}/{dia}/{ano}"

    # -----------------------------------------------------------------
    # FLUJO 1: RESIDENCIA Y TRABAJO USA (USCIS - LEY DE AJUSTE) -> 3 PDFs
    # -----------------------------------------------------------------
    if cliente.tramite_tipo == "paquete_completo_uscis":
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)
        empleo_ingles = traducir_historial_laboral_ia(cliente.empleo_cuba_espanol)

        # 1. G-1450 (Residencia - $1440)
        rellenar_planilla_pdf("g1450.pdf", {
            "form1[0].#subform[0].FamilyName[0]": apellido1,
            "form1[0].#subform[0].GivenName[0]": nombre1,
            "form1[0].#subform[0].MiddleName[0]": nombre2,
            "form1[0].#subform[0].AuthorizedPaymentAmt[0]": "1440"
        }, "temp_g1450.pdf")

        # 2. I-485 (Residencia Permanente)
        rellenar_planilla_pdf("i485.pdf", {
            "form1[0].#subform[0].Page1[0].Pt1Line3a_FamilyName[0]": apellido1,
            "form1[0].#subform[0].Page1[0].Pt1Line3b_GivenName[0]": nombre1,
            "form1[0].#subform[0].Page1[0].Pt1Line3c_MiddleName[0]": nombre2,
            "form1[0].#subform[0].Page1[0].AlienRegistrationNumber[0]": anumber_limpio,
            "form1[0].#subform[0].Page1[0].Pt1Line8_DateOfBirth[0]": fecha_usa,
            "form1[0].#subform[0].Page3[0].Pt3Line1_RecentEmployer[0]": empleo_ingles
        }, "temp_i485.pdf")

        # 3. I-765 (Permiso de Trabajo)
        rellenar_planilla_pdf("i765.pdf", {
            "form1[0].Page1[0].Line1a_FamilyName[0]": apellido1,
            "form1[0].Page1[0].Line1b_GivenName[0]": nombre1,
            "form1[0].Page1[0].Line1c_MiddleName[0]": nombre2,
            "form1[0].Page2[0].AlienRegistrationNumber[0]": anumber_limpio
        }, "temp_i765.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i485.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i765.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)

    # -----------------------------------------------------------------
    # FLUJO 2: TRÁMITE CONSULAR (PASAPORTE CUBANO) -> 1 PDF
    # -----------------------------------------------------------------
    elif cliente.tramite_tipo == "pasaporte_cubano":
        pasaporte_limpio = validar_y_limpiar_pasaporte(cliente.pasaporte_actual, es_obligatorio=True)
        provincia_limpia = corregir_y_sanear_texto(cliente.provincia_cuba, es_obligatorio=True, nombre_campo="Provincia de Origen")
        ano_salida_limpio = corregir_y_sanear_texto(cliente.ano_salida_cuba, es_obligatorio=True, nombre_campo="Año de Salida")
        
        empleo_espanol_limpio = corregir_y_sanear_texto(
            cliente.empleo_cuba_espanol, 
            es_obligatorio=True, 
            nombre_campo="Último empleo o estudios en Cuba"
        )

        campos_pasaporte = {
            "Primer nombre": nombre1,
            "Segundo nombre": nombre2,
            "Primer apellido": apellido1,
            "Segundo apellido": apellido2,
            "DíaRow1": dia,
            "MesRow1": mes,
            "AñoRow1": ano,
            "Número de Pasaporte": pasaporte_limpio,
            "Provincia": provincia_limpia,
            "AñoRow": ano_salida_limpio,
            "Profesión u oficio": empleo_espanol_limpio
        }
        
        rellenar_planilla_pdf("pasaporte.pdf", campos_pasaporte, id_archivo_salida)
# -----------------------------------------------------------------
    # FLUJO 3: CIUDADANÍA AMERICANA (USCIS - N-400) -> 2 PDFs
    # -----------------------------------------------------------------
    elif cliente.tramite_tipo == "naturalizacion_n400":
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)
        
        # 1. G-1450 (Ciudadanía - $710)
        rellenar_planilla_pdf("g1450.pdf", {
            "form1[0].#subform[0].FamilyName[0]": apellido1,
            "form1[0].#subform[0].GivenName[0]": nombre1,
            "form1[0].#subform[0].MiddleName[0]": nombre2,
            "form1[0].#subform[0].AuthorizedPaymentAmt[0]": "710"
        }, "temp_g1450.pdf")

        # 2. N-400 (Naturalización)
        rellenar_planilla_pdf("n400.pdf", {
            "form1[0].#subform[0].P2_Line1_FamilyName[0]": apellido1,
            "form1[0].#subform[0].P2_Line1_GivenName[0]": nombre1,
            "form1[0].#subform[0].P2_Line1_MiddleName[0]": nombre2,
            "form1[0].#subform[1].#area[1].Line1_AlienNumber[1]": anumber_limpio,
            "form1[0].#subform[1].P2_Line8_DateOfBirth[0]": fecha_usa
        }, "temp_n400.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_n400.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)
            
    else:
        raise HTTPException(status_code=400, detail="El trámite comercial solicitado no existe en SAVE CUBA.")

# Endpoint principal de procesamiento
@app.post("/procesar_tramite")
async def procesar(cliente: DatosClienteUnificados):
    id_unico = f"tramite_{cliente.primer_apellido}_{cliente.primer_nombre}.pdf"
    try:
        ejecutar_mapeo_y_guardado(cliente, id_unico)
        # Limpieza de archivos temporales si existen
        for tmp in ["temp_g1450.pdf", "temp_i485.pdf", "temp_i765.pdf", "temp_n400.pdf"]:
            ruta_tmp = os.path.join(SALIDAS_DIR, tmp)
            if os.path.exists(ruta_tmp):
                os.remove(ruta_tmp)
        return {"status": "success", "archivo": id_unico}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
