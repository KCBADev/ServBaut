import streamlit as st


def mostrar():
    st.title("🔒 Aviso de Confidencialidad")

    st.markdown("""
La información registrada y consultada en esta aplicación (datos de clientes,
vehículos, diagnósticos, cotizaciones y notas de servicio) es **confidencial**
y de uso exclusivo para la operación interna de Servicio Bautista.

**Compromisos del usuario:**
- No compartir, copiar ni distribuir información de clientes fuera del sistema.
- Usar los datos únicamente para los fines del servicio solicitado.
- No divulgar credenciales de acceso.

El uso de esta aplicación implica la aceptación de este aviso.
""")

    if "aviso_aceptado" not in st.session_state:
        st.session_state.aviso_aceptado = False

    if st.session_state.aviso_aceptado:
        st.success("Ya aceptaste el Aviso de Confidencialidad.")
    elif st.checkbox("He leído y acepto el Aviso de Confidencialidad"):
        st.session_state.aviso_aceptado = True
        st.rerun()
