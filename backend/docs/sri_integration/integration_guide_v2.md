# Guía de Integración - Facturación Electrónica SRI (Ecuador)

## Endpoint: `create_and_process_invoice_complete`

Esta guía detalla el proceso para integrar el sistema RutaFact con aplicaciones externas para la emisión de facturas electrónicas autorizadas por el SRI.

---

### 1. Información General del Endpoint

- **URL:** `POST /api/sri/documents/create_and_process_invoice_complete/`
- **Funcionalidad:** Crea un registro de factura en la base de datos, genera el XML, lo firma digitalmente y lo envía al SRI para su autorización en una sola llamada.
- **Ambiente:** Depende de la configuración de la empresa (TEST o PRODUCTION).
- **Proceso Interno:** Creación → XML → Firma → Envío SRI → Consulta Autorización.
- **Tiempo de respuesta:** 1-3 segundos (Sincrónico) o instantáneo (Asincrónico).

---

### 2. Autenticación

El sistema soporta dos tipos de tokens en el header `Authorization`:

#### A. Token VSR (Recomendado para integraciones de una sola empresa)
- **Formato:** `Authorization: Token vsr_XXXXXXXXXXXXXXXXX`
- **Ventaja:** Detecta automáticamente la empresa vinculada al token.
- **Requisito:** NO enviar el campo `company` en el JSON del request.

#### B. Token de Usuario (Recomendado para sistemas multi-empresa)
- **Formato:** `Authorization: Token XXXXXXXXXXXXXXXXX`
- **Requisito:** Obligatorio enviar el campo `company` (ID de la empresa) en el JSON.

---

### 3. Estructura del Request (JSON)

#### Campos Principales
| Campo | Tipo | Obligatorio | Descripción | Validación |
| :--- | :--- | :---: | :--- | :--- |
| `issue_date` | string | SI | Fecha de emisión (YYYY-MM-DD) | Formato de fecha válido |
| `customer_identification_type` | string | SI | Tipo de identificación | ["04", "05", "06", "07", "08"] |
| `customer_identification` | string | SI | Número de identificación | Según el tipo |
| `customer_name` | string | SI | Nombre o Razón Social | Máximo 300 caracteres |
| `customer_address` | string | NO | Dirección del cliente | Opcional |
| `customer_email` | string | NO | Email para envío de XML/PDF | Opcional |
| `customer_phone` | string | NO | Teléfono del cliente | Opcional |
| `send_email` | boolean | NO | Enviar email automáticamente | Default: `true` |
| `company` | integer | * | ID de la empresa | Obligatorio solo si se usa Token de Usuario |
| `items` | array | SI | Lista de productos/servicios | Mínimo 1 item |

#### Estructura de Items
| Campo | Tipo | Obligatorio | Descripción |
| :--- | :--- | :---: | :--- |
| `main_code` | string | SI | Código principal del producto |
| `auxiliary_code` | string | NO | Código auxiliar |
| `description` | string | SI | Descripción del producto/servicio |
| `quantity` | number | SI | Cantidad (hasta 6 decimales) |
| `unit_price` | number | SI | Precio unitario (hasta 6 decimales) |
| `discount` | number | NO | Valor del descuento (opcional) |

---

### 4. Codificación del SRI (Ecuador)

#### Tipos de Identificación del Cliente
| Código | Tipo | Descripción | Validación |
| :--- | :--- | :--- | :--- |
| **04** | RUC | Registro Único de Contribuyentes | 13 dígitos |
| **05** | Cédula | Cédula de Identidad | 10 dígitos |
| **06** | Pasaporte | Pasaporte del cliente | Alfanumérico |
| **07** | Consumidor Final | Ventas sin datos (hasta $50.00) | N/A |
| **08** | ID Exterior | Identificación para extranjeros | Alfanumérico |

#### Estados del Documento
El sistema maneja los siguientes estados internos:
1. `DRAFT`: Creado inicialmente.
2. `GENERATED`: XML generado.
3. `SIGNED`: XML firmado digitalmente.
4. `SENT`: Enviado al SRI.
5. `AUTHORIZED`: Autorizado y legalmente válido.
6. `REJECTED`: Rechazado por el SRI (errores de validación).
7. `ERROR`: Error interno o de conexión.

---

### 5. Cálculos y Reglas de Negocio

El sistema realiza automáticamente los siguientes cálculos:
- **IVA:** Actualmente configurado al **15%** (Ecuador 2024+).
- **Subtotal por Item:** `(quantity * unit_price) - discount`.
- **Total Impuestos:** Suma de IVAs calculados por item.
- **Total Factura:** `Subtotal sin impuestos + Total Impuestos`.
- **Clave de Acceso:** Se genera automáticamente una clave de 49 dígitos siguiendo el estándar del SRI.

---

### 6. Respuestas del Sistema

#### Respuesta Exitosa (HTTP 201)
```json
{
  "success": true,
  "message": "Factura creada y enviada al SRI exitosamente",
  "invoice": {
    "id": 175,
    "number": "001-001-000001102",
    "access_key": "0408202501123456789000120010010000011021234567812",
    "customer": "JUAN CARLOS PÉREZ",
    "total": 115.0,
    "status": "Autorizado",
    "date": "2025-08-04 17:39"
  }
}
```

#### Respuesta de Procesamiento Asíncrono (HTTP 201)
*Si la empresa tiene habilitado `SRI_ASYNC_PROCESSING`.*
```json
{
  "success": true,
  "message": "Factura recibida y puesta en cola para procesamiento (SRI asíncrono)",
  "invoice": {
    "id": 175,
    "status": "QUEUED",
    ...
  }
}
```

#### Error de Validación (HTTP 422)
```json
{
  "error": "VALIDATION_ERROR",
  "message": "Missing required fields",
  "missing_fields": ["items"]
}
```

---

### 7. Pasos para una Integración Exitosa

1. **Configuración de Empresa:** Asegúrese de que la empresa tenga:
   - RUC, Razón Social y Dirección configurados.
   - Certificado digital (.p12) cargado y vigente.
   - Secuenciales de facturación inicializados.
2. **Obtención del Token:** Solicite su Token VSR en el panel administrativo.
3. **Pruebas en Ambiente TEST:** Realice sus primeras llamadas apuntando al ambiente de pruebas del SRI.
4. **Validación de Respuesta:** Siempre verifique el campo `success` y `status`. Si el estado es `REJECTED` o `ERROR`, consulte el detalle en el log del sistema o en el endpoint de consulta de estado.

---

### 8. Límites y Restricciones
- **Timeout:** Las llamadas sincrónicas pueden tardar hasta 10 segundos.
- **Concurrencia:** Máximo 10 requests simultáneos por token (recomendado).
- **Items:** Máximo 100 items por factura.
