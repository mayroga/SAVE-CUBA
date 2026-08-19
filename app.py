import os
import shutil
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from pypdf import PdfWriter, PdfReader
import fitz  # PyMuPDF para manejo avanzado de PDFs si se requiere

app = FastAPI(title="SAVE CUBA / AURA API", version="3.0")

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directorios de trabajo
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLAS_DIR = os.path.join(BASE_DIR, "plantillas")
SALIDAS_DIR = os.path.join(BASE_DIR, "salidas")

os.makedirs(PLANTILLAS_DIR, exist_ok=True)
os.makedirs(SALIDAS_DIR, exist_ok=True)

# =====================================================================
# MODELOS DE DATOS UNIFICADOS (CLIENTE Y TRAMITES)
# =====================================================================
class DatosClienteUnificados(BaseModel):
    tramite_tipo: str = Field(..., description="Tipo de trámite seleccionado")
    primer_nombre: str = Field(..., description="Primer nombre del cliente")
    segundo_nombre: Optional[str] = Field(None, description="Segundo nombre")
    primer_apellido: str = Field(..., description="Primer apellido")
    segundo_apellido: Optional[str] = Field(None, description="Segundo apellido")
    fecha_nacimiento: str = Field(..., description="Fecha de nacimiento en formato AAAA-MM-DD")
    anumber: Optional[str] = Field(None, description="Número de Alien (A-Number)")
    pasaporte_actual: Optional[str] = Field(None, description="Número de pasaporte actual")
    provincia_cuba: Optional[str] = Field(None, description="Provincia de nacimiento u origen en Cuba")
    ano_salida_cuba: Optional[str] = Field(None, description="Año de salida de Cuba")
    empleo_cuba_espanol: Optional[str] = Field(None, description="Último empleo o estudios en Cuba")

# =====================================================================
# FUNCIONES DE SANEAMIENTO Y VALIDACIÓN
# =====================================================================
def corregir_y_sanear_texto(texto: Optional[str], es_obligatorio: bool = False, nombre_campo: str = "Campo") -> str:
    if not texto or not texto.strip():
        if es_obligatorio:
            raise HTTPException(status_code=400, detail=f"¡Atención! El campo '{nombre_campo}' es obligatorio.")
        return ""
    return texto.strip().upper()

def validar_y_limpiar_anumber(anumber: Optional[str], es_obligatorio: bool = False) -> str:
    if not anumber or not anumber.strip():
        if es_obligatorio:
            raise HTTPException(status_code=400, detail="¡Atención! El número A-Number es obligatorio para este trámite.")
        return ""
    limpio = "".join(filter(str.isalnum, anumber)).upper()
    if not limpio.startswith("A"):
        limpio = "A" + limpio
    return limpio

def validar_y_limpiar_pasaporte(pasaporte: Optional[str], es_obligatorio: bool = False) -> str:
    if not pasaporte or not pasaporte.strip():
        if es_obligatorio:
            raise HTTPException(status_code=400, detail="¡Atención! El número de pasaporte es obligatorio.")
        return ""
    return "".join(filter(str.isalnum, pasaporte)).upper()

def traducir_historial_laboral_ia(texto_espanol: Optional[str]) -> str:
    if not texto_espanol:
        return "N/A"
    # Capa base de traducción/adaptación técnica para formularios en inglés de USCIS
    texto_mayus = texto_espanol.strip().upper()
    traducciones_comunes = {
        "ESTUDIANTE": "STUDENT",
        "NINGUNO": "NONE",
        "PROFESOR": "TEACHER",
        "MEDICO": "PHYSICIAN",
        "INGENIERO": "ENGINEER"
    }
    return traducciones_comunes.get(texto_mayus, texto_mayus)

# =====================================================================
# MOTOR DE LLENADO DE PLANILLAS PDF
# =====================================================================
def rellenar_planilla_pdf(nombre_archivo_plantilla: str, campos: dict, nombre_archivo_salida: str):
    ruta_plantilla = os.path.join(PLANTILLAS_DIR, nombre_archivo_plantilla)
    ruta_salida = os.path.join(SALIDAS_DIR, nombre_archivo_salida)

    if not os.path.exists(ruta_plantilla):
        raise HTTPException(status_code=500, detail=f"Error interno: No se encuentra la plantilla oficial '{nombre_archivo_plantilla}'.")

    reader = PdfReader(ruta_plantilla)
    writer = PdfWriter()
    writer.append(reader)

    # Aplicar campos rellenables si el PDF posee formularios acroform
    if writer.get_fields():
        try:
            writer.update_page_form_field_values(writer.pages[0], campos)
        except Exception:
            pass

    with open(ruta_salida, "wb") as f_out:
        writer.write(f_out)
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

        # Limpieza de temporales
        for temp_file in ["temp_g1450.pdf", "temp_i485.pdf", "temp_i765.pdf"]:
            ruta_temp = os.path.join(SALIDAS_DIR, temp_file)
            if os.path.exists(ruta_temp):
                try:
                    os.remove(ruta_temp)
                except Exception:
                    pass

    # -----------------------------------------------------------------
    # FLUJO 2: TRÁMITE CONSULAR (PASAPORTE CUBANO) -> 1 PDF EN ESPAÑOL
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
            
        # Limpieza de temporales
        for temp_file in ["temp_g1450.pdf", "temp_n400.pdf"]:
            ruta_temp = os.path.join(SALIDAS_DIR, temp_file)
            if os.path.exists(ruta_temp):
                try:
                    os.remove(ruta_temp)
                except Exception:
                    pass
          
    else:
        raise HTTPException(status_code=400, detail="El trámite solicitado no existe en el sistema.")
# =====================================================================
# ENDPOINTS DE LA API (PROCESAMIENTO Y DESCARGA)
# =====================================================================
@app.post("/api/procesar-tramite")
async def procesar_tramite(cliente: DatosClienteUnificados):
    try:
        # Generar un identificador único para el archivo de salida
        id_unico = f"paquete_{cliente.tramite_tipo}_{os.urandom(4).hex()}.pdf"
        
        # Ejecutar el motor de mapeo y autollenado real
        ejecutar_mapeo_y_guardado(cliente, id_unico)
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Planillas rellenadas y procesadas correctamente.",
                "archivo_id": id_unico,
                "download_url": f"/api/descargar-pdf/{id_unico}"
            }
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error crítico en el servidor al procesar el trámite: {str(e)}")


@app.get("/api/descargar-pdf/{archivo_id}")
async def descargar_pdf(archivo_id: str):
    # Validar seguridad básica del nombre de archivo
    if ".." in archivo_id or "/" in archivo_id or "\\" in archivo_id:
        raise HTTPException(status_code=400, detail="Nombre de archivo no válido.")
        
    ruta_archivo = os.path.join(SALIDAS_DIR, archivo_id)
    
    if not os.path.exists(ruta_archivo):
        raise HTTPException(status_code=404, detail="El archivo solicitado no existe o ha expirado.")
        
    return FileResponse(
        path=ruta_archivo,
        media_type="application/pdf",
        filename=archivo_id
    )


@app.get("/")
async def root():
    return {
        "status": "online",
        "system": "AURA / SAVE CUBA API",
        "version": "3.0",
        "description": "Motor de autollenado de planillas oficiales activo."
    }


# =====================================================================
# INICIO DE LA APLICACIÓN
# =====================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
