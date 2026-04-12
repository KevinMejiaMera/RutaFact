# RutaFact - Ecosistema de Facturación y Retención Binacional

Este repositorio contiene el sistema completo del **Facturador Electrónico RutaFact**, estructurado ahora como un **monorepo** para mantener de forma separada el lado móvil y los servicios del backend en su propio entorno.

## Estructura del Proyecto

- **`backend/`**: Contiene todo el código del API Web en Django (Sistema de facturación). Aquí encontrarás la configuración de Docker, el archivo `manage.py`, variables de entorno y todas las apps (`invoicing`, `companies`, `sri_integration`, etc.).
- **`movil/`**: Contiene el código fuente de la Aplicación Móvil en Flutter. La aplicación móvil se conectará directamente a las APIs expuestas por la carpeta `backend`.

Esto asegura que "no se mezclen los dos frameworks" como has solicitado, manteniendo el código ordenado y escalable.

## Ejecución del Backend

Para levantar tu sistema de facturación ingresa a la carpeta del backend y usa Docker:

```bash
cd backend
docker-compose up -d --build
```
O si estás usando entorno virtual, ingresa a `backend/`, activa el entorno y corre el servidor de desarrollo en esa misma ruta.

## Desarrollo Móvil (Flutter)

El frontend de la app está ubicado en la carpeta `movil`. Para comenzar a trabajar aquí:

1. Entra a la carpeta: `cd movil`
2. Si aún no está inicializado el proyecto, puedes hacer un `flutter create .` (teniendo Flutter preinstalado en tu máquina).
3. Asegúrate que tu configuración apunte a los endpoints del servidor web que levantes desde la carpeta backend.
