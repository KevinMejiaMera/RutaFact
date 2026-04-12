from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from apps.companies.models import CompanyAPIToken, Company
from apps.api.user_company_helper import get_user_companies_exact


@api_view(['POST'])
@permission_classes([AllowAny])
def token_login(request):
    """
    Login que retorna tokens disponibles para el usuario
    
    POST /api/auth/login/
    {
        "email": "usuario@gmail.com",
        "password": "password"
    }
    
    Response:
    {
        "user_token": "372a72b56b8bdf7b2d626d3a0df82c37c1600804",
        "company_tokens": [
            {
                "company_id": 1,
                "company_name": "JHONY VICENTE",
                "token": "vsr_ABC123...",
                "recommended": false
            },
            {
                "company_id": 2, 
                "company_name": "pixel",
                "token": "vsr_XYZ789...",
                "recommended": true
            }
        ],
        "user": {
            "email": "usuario@gmail.com",
            "name": "Usuario Test"
        }
    }
    """
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({
            'error': 'EMAIL_PASSWORD_REQUIRED',
            'message': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Autenticar usuario
    user = authenticate(username=email, password=password)
    if not user:
        return Response({
            'error': 'INVALID_CREDENTIALS',
            'message': 'Invalid email or password'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    if not user.is_active:
        return Response({
            'error': 'USER_INACTIVE',
            'message': 'User account is disabled'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Obtener/crear token de usuario
    user_token, created = Token.objects.get_or_create(user=user)
    
    # Obtener empresas asignadas al usuario
    user_companies = get_user_companies_exact(user)
    
    # Obtener tokens de empresa para las empresas del usuario
    company_tokens = []
    recommended_company = None
    
    for company in user_companies:
        # Crear token de empresa si no existe
        company_token, created = CompanyAPIToken.objects.get_or_create(
            company=company,
            defaults={
                'name': f'Auto-generated token for {company.business_name}',
                'is_active': True
            }
        )
        
        company_tokens.append({
            'company_id': company.id,
            'company_name': company.business_name,
            'company_ruc': company.ruc,
            'token': company_token.key,
            'recommended': recommended_company is None  # Primera empresa como recomendada
        })
        
        if recommended_company is None:
            recommended_company = company
    
    return Response({
        'success': True,
        'message': 'Login successful',
        'user_token': user_token.key,
        'company_tokens': company_tokens,
        'user': {
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'full_name': f"{user.first_name} {user.last_name}".strip()
        },
        'recommendations': {
            'use_company_tokens': True,
            'recommended_company': recommended_company.id if recommended_company else None,
            'message': 'Use company tokens for better security and simpler URLs'
        }
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
def token_logout(request):
    """
    Logout - invalida token actual
    """
    if hasattr(request, 'auth') and request.auth:
        request.auth.delete()
        return Response({
            'success': True,
            'message': 'Logged out successfully'
        })
    
    return Response({
        'success': True,
        'message': 'No active session found'
    })


@api_view(['GET'])
def token_profile(request):
    """
    Obtener información del token actual
    """
    from apps.api.authentication import VirtualCompanyUser, get_token_info
    
    token_info = get_token_info(request)
    
    if isinstance(request.user, VirtualCompanyUser):
        # Token de empresa
        company_token = request.company_token
        return Response({
            'token_type': 'company',
            'company': {
                'id': company_token.company.id,
                'name': company_token.company.business_name,
                'ruc': company_token.company.ruc
            },
            'token': {
                'name': company_token.name,
                'created_at': company_token.created_at,
                'last_used_at': company_token.last_used_at,
                'total_requests': company_token.total_requests,
                'permissions': company_token.get_permissions()
            },
            'capabilities': {
                'needs_company_id': False,
                'message': 'This token is tied to a specific company'
            }
        })
    else:
        # Token de usuario
        user_companies = get_user_companies_exact(request.user)
        return Response({
            'token_type': 'user',
            'user': {
                'id': request.user.id,
                'email': request.user.email,
                'full_name': f"{request.user.first_name} {request.user.last_name}".strip()
            },
            'companies': [
                {
                    'id': company.id,
                    'name': company.business_name,
                    'ruc': company.ruc
                }
                for company in user_companies
            ],
            'capabilities': {
                'needs_company_id': True,
                'message': 'This token can access multiple companies, specify company_id in requests'
            }
        })


@api_view(['GET'])
@permission_classes([AllowAny])
def auth_status(request):
    """
    Verificar estado de autenticación sin requerir login
    """
    auth_header = request.META.get('HTTP_AUTHORIZATION')
    
    if not auth_header:
        return Response({
            'authenticated': False,
            'message': 'No authorization header provided'
        })
    
    try:
        from apps.api.authentication import DualTokenAuthentication
        auth = DualTokenAuthentication()
        user_auth = auth.authenticate(request)
        
        if user_auth:
            user, token = user_auth
            from apps.api.authentication import VirtualCompanyUser
            
            if isinstance(user, VirtualCompanyUser):
                return Response({
                    'authenticated': True,
                    'token_type': 'company',
                    'company_name': user.company.business_name
                })
            else:
                return Response({
                    'authenticated': True,
                    'token_type': 'user',
                    'user_email': user.email
                })
        else:
            return Response({
                'authenticated': False,
                'message': 'Invalid token'
            })
    except Exception as e:
        return Response({
            'authenticated': False,
            'message': 'Authentication error',
            'error': str(e)
        })
@api_view(['POST'])
@permission_classes([AllowAny])
def token_register(request):
    """
    Registro de usuario desde móvil
    
    POST /api/auth/register/
    {
        "email": "nuevo@gmail.com",
        "password": "password123",
        "first_name": "Nombre",
        "last_name": "Apellido"
    }
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    email = request.data.get('email')
    password = request.data.get('password')
    first_name = request.data.get('first_name', '')
    last_name = request.data.get('last_name', '')
    
    if not email or not password:
        return Response({
            'success': False,
            'error': 'EMAIL_PASSWORD_REQUIRED',
            'message': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)
        
    if User.objects.filter(email=email).exists():
        return Response({
            'success': False,
            'error': 'EMAIL_EXISTS',
            'message': 'A user with this email already exists'
        }, status=status.HTTP_400_BAD_REQUEST)
        
    # Crear usuario
    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name
    )
    
    # Crear asignación (sala de espera)
    from apps.users.models import UserCompanyAssignment, AdminNotification
    UserCompanyAssignment.objects.create(user=user, status='waiting')
    
    # Notificar a los admins
    try:
        AdminNotification.create_user_registered_notification(user)
    except Exception as e:
        print(f"Error creating admin notification: {e}")
    
    # Crear token
    token, created = Token.objects.get_or_create(user=user)
    
    return Response({
        'success': True,
        'message': 'User registered successfully. Waiting for admin approval.',
        'token': token.key,
        'user': {
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name
        }
    }, status=status.HTTP_201_CREATED)
