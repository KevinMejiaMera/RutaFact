# RutaFact Mobile App

Esta carpeta está destinada para la aplicación móvil construida en Flutter.

## Inicializar el Proyecto

Para inicializar la estructura base de Flutter en esta carpeta (asegúrate de tener instalado Flutter en tu sistema), abre tu terminal en este directorio y ejecuta:

```bash
flutter create .
```

Una vez creado, este será el frontend móvil que consuma la API del facturador (ahora ubicado en la raíz del repositorio).

## Conexión API - Backend (Django)

El backend expone todas las APIs necesarias para facturación electrónica (como lo construimos previamente). 
Configura tus variables de entorno locales en el frontend de Flutter para apuntar al backend:
- `API_BASE_URL` = `http://10.0.2.2:8000/api/` (para Android Emulator)
- `API_BASE_URL` = `http://localhost:8000/api/` (para web/iOS)
