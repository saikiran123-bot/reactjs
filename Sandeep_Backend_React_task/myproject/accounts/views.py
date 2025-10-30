import json
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from .models import LogEntry, LoginEntry, Topic, TopicRequest
import logging
import re
from django.conf import settings
from confluent_kafka.admin import AdminClient, NewTopic, NewPartitions

from .models import Topic, TopicRequest

KAFKA_BOOTSTRAP = [
    'sandeep.infra.alephys.com:12091',
    'sandeep.infra.alephys.com:12092',
    # 'navyanode3.infra.alephys.com:9094',
]

# conf = {
#     'bootstrap.servers': 'navyanode3.infra.alephys.com:9094',
#     'security.protocol': 'SSL',
#     'ssl.ca.location': r'C:\Users\91913\Desktop\AlephysReact\backend\ca-cert.pem',
#     'ssl.endpoint.identification.algorithm': 'none',
# }

logger = logging.getLogger(__name__)

# One-time cleanup of existing topics (run once, then comment out)
# if Topic.objects.exists():
#     admin_client = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP})
#     for topic in Topic.objects.all():
#         try:
#             admin_client.delete_topics([topic.name])
#             logger.info(f"Cleaned up existing Kafka topic '{topic.name}'")
#         except Exception as e:
#             logger.error(f"Failed to clean up Kafka topic '{topic.name}': {e}")
#         topic.delete()
#     logger.info("All existing topics cleaned up from database")

@csrf_exempt
def login_view_api(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            logger.info(f"User {username} logged in successfully")

            LoginEntry.objects.create(
                username=username,
                login_time=timezone.now(),
                success=True
            )

            if user.is_superuser:
                role = "admin"
            else:
                role = "user"

            return JsonResponse({
                "success": True,
                "message": "Login successful",
                "role": role
            })

        else:
            logger.warning(f"Failed login attempt for {username}")
            LoginEntry.objects.create(
                username=username,
                login_time=timezone.now(),
                success=False
            )
            return JsonResponse({
                "success": False,
                "message": "Invalid credentials"
            })

    return JsonResponse({"error": "Invalid request"}, status=400)

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            logger.info(f"User {username} logged in successfully")
            LoginEntry.objects.create(
                username=username,
                login_time=timezone.now(),
                success=True
            )
            if user.is_superuser:
                return JsonResponse({"success": True, "message": "Login successful", "redirect": "/admin_dashboard/"})
            return JsonResponse({"success": True, "message": "Login successful", "redirect": "/home/"})
        else:
            logger.warning(f"Failed login attempt for {username}")
            LoginEntry.objects.create(
                username=username,
                login_time=timezone.now(),
                success=False
            )
            return JsonResponse({"success": False, "message": "Invalid credentials"})
    return render(request, "login.html")

@csrf_exempt
def logout_view_api(request):
    if request.user.is_authenticated:
        logger.info(f"User {request.user.username} logged out")
        logout(request)
        request.session.flush()
    return JsonResponse({"success": True, "message": "Logged out successfully"})

@login_required
def logout_view(request):
    if request.user.is_authenticated:
        logger.info(f"User {request.user.username} logged out")
        logout(request)
        request.session.flush()
    return redirect("login")

@csrf_exempt
def home_api(request):
    user = request.user

    if not user.is_authenticated:
        return JsonResponse({"success": False, "message": "User not authenticated."}, status=403)

    # Handle GET requests
    if request.method == "GET":
        print(" home_api called by:", user.username)

        topics = Topic.objects.filter(is_active=True, created_by=user)
        approved_requests = TopicRequest.objects.filter(requested_by=user, status="APPROVED")

        # Identify approved but uncreated topics
        uncreated_requests = [
            {
                "id": req.id,
                "topic_name": req.topic_name,
                "partitions": req.partitions,
                "status": req.status,
            }
            for req in approved_requests
            if not Topic.objects.filter(name=req.topic_name, is_active=True, created_by=user).exists()
        ]

        created_topics = [
            {
                "id": topic.id,
                "name": topic.name,
                "partitions": topic.partitions,
            }
            for topic in topics
        ]

        # user role
        role = "admin" if user.is_superuser else "user"

        data = {
            "success": True,
            "username": user.username,
            "role": role,  # Include role in response
            "uncreated_requests": uncreated_requests,
            "created_topics": created_topics,
        }
        return JsonResponse(data, safe=False)

    elif request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return JsonResponse({"success": False, "message": "Invalid JSON payload."}, status=400)

        topic_name = data.get("topic_name", "").strip()
        partitions = data.get("partitions")

        if not topic_name or not partitions:
            return JsonResponse({"success": False, "message": "Please fill all fields."}, status=400)

        try:
            partitions = int(partitions)
            if partitions < 1:
                return JsonResponse({"success": False, "message": "Partitions must be at least 1."}, status=400)

            # Check duplicate pending request
            if TopicRequest.objects.filter(
                topic_name=topic_name,
                requested_by=user,
                status="PENDING"
            ).exists():
                return JsonResponse({"success": False, "message": "You already have a pending request for this topic."}, status=400)

            # Create new request
            TopicRequest.objects.create(
                topic_name=topic_name,
                partitions=partitions,
                requested_by=user,
                status="PENDING",
            )

            logger.info(f"Topic request for '{topic_name}' submitted by {user.username}")
            return JsonResponse({"success": True, "message": "Topic creation request submitted. Waiting for admin approval."})

        except ValueError:
            return JsonResponse({"success": False, "message": "Invalid number of partitions."}, status=400)

    else:
        return JsonResponse({"success": False, "message": "Unsupported request method."}, status=400)   
    
@login_required
def home(request):
    if request.user.is_superuser:
        return redirect("admin_dashboard")
    context = {
        "topics": Topic.objects.filter(is_active=True, created_by=request.user),
        "username": request.user.username,
    }
    if request.method == "POST":
        topic_name = request.POST.get("topic_name").strip()
        partitions = request.POST.get("partitions")
        if topic_name and partitions:
            try:
                partitions = int(partitions)
                if partitions < 1:
                    context["error"] = "Partitions must be at least 1."
                elif TopicRequest.objects.filter(topic_name=topic_name, requested_by=request.user, status='PENDING').exists():
                    context["error"] = "You already have a pending request for this topic."
                else:
                    TopicRequest.objects.create(
                        topic_name=topic_name,
                        partitions=partitions,
                        requested_by=request.user
                    )
                    context["success"] = "Topic creation request submitted. Waiting for admin approval."
                    logger.info(f"Topic request for {topic_name} submitted by {request.user.username}")
            except ValueError:
                context["error"] = "Invalid number of partitions."
        else:
            context["error"] = "Please fill all fields."
    
    # Reset approved requests to ensure no stale data
    approved_requests = TopicRequest.objects.filter(requested_by=request.user, status='APPROVED')
    uncreated_requests = []
    for req in approved_requests:
        if not Topic.objects.filter(name=req.topic_name, is_active=True, created_by=request.user).exists():
            uncreated_requests.append(req)
    context["uncreated_requests"] = uncreated_requests

    # Add created topics to context
    context["created_topics"] = Topic.objects.filter(is_active=True, created_by=request.user)

    return render(request, "home.html", context)


@csrf_exempt
def admin_dashboard_api(request):
    if request.method == "GET":
        print("admin_dashboard_api called by:", request.user)
        data = {
            "pending_requests": list(
                TopicRequest.objects.filter(status="PENDING")
                .order_by("-requested_at")
                .values("id", "topic_name", "partitions", "requested_by__username")
            ),
            "created_topics": list(
                Topic.objects.filter(is_active=True)
                .values("id", "name", "partitions", "created_by__username")
            ),
            "username": getattr(request.user, "username", "admin"),
        }
        return JsonResponse(data)

    elif request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
            topic_name = data.get("topic_name", "").strip()
            partitions = data.get("partitions")

            if not topic_name or not partitions:
                return JsonResponse({"success": False, "message": "Missing topic name or partitions."}, status=400)

            partitions = int(partitions)
            if partitions < 1:
                return JsonResponse({"success": False, "message": "Partitions must be at least 1."}, status=400)

            if Topic.objects.filter(name=topic_name, is_active=True).exists():
                return JsonResponse({"success": False, "message": f"Topic '{topic_name}' already exists."}, status=400)

            # Kafka topic creation
            admin_client = AdminClient({'bootstrap.servers': ','.join(KAFKA_BOOTSTRAP)})
            new_topic = NewTopic(topic_name, num_partitions=partitions, replication_factor=1)
            fs = admin_client.create_topics([new_topic])
            for _, f in fs.items():
                f.result()

            # Save to DB
            Topic.objects.create(
                name=topic_name,
                partitions=partitions,
                created_by=request.user,
                production="Active",
                consumption="Active",
                followers=1,
                observers=0,
                last_produced=timezone.now(),
            )

            # ✅ Return updated dashboard data
            updated_data = {
                "success": True,
                "message": f"Topic '{topic_name}' created successfully!",
                "pending_requests": list(
                    TopicRequest.objects.filter(status="PENDING")
                    .order_by("-requested_at")
                    .values("id", "topic_name", "partitions", "requested_by__username")
                ),
                "created_topics": list(
                    Topic.objects.filter(is_active=True)
                    .values("id", "name", "partitions", "created_by__username")
                ),
            }

            return JsonResponse(updated_data)

        except Exception as e:
            logger.error(f"Error creating topic: {e}")
            return JsonResponse({"success": False, "message": str(e)}, status=500)


@login_required
def  admin_dashboard(request):
    if not request.user.is_superuser:
        return redirect("home")
    context = {
        "topics": Topic.objects.filter(is_active=True, created_by=request.user),
        "username": request.user.username,
        "pending_requests": TopicRequest.objects.filter(status='PENDING').order_by('-requested_at'),
        "created_topics": Topic.objects.filter(is_active=True),
    }
    if request.method == "POST":
        topic_name = request.POST.get("topic_name").strip()
        partitions = request.POST.get("partitions")
        if topic_name and partitions:
            try:
                partitions = int(partitions)
                if partitions < 1:
                    context["error"] = "Partitions must be at least 1."
                elif Topic.objects.filter(name=topic_name, is_active=True).exists():
                    context["error"] = f"Topic '{topic_name}' already exists."
                else:
                    try:
                        admin_client = AdminClient({
                            'bootstrap.servers': ','.join(KAFKA_BOOTSTRAP)
                        })
                        # admin_client = AdminClient(conf);
                        new_topic = NewTopic(topic_name, num_partitions=partitions, replication_factor=1)
                        admin_client.create_topics([new_topic])
                        logger.info(f"Admin created Kafka topic '{topic_name}' with {partitions} partitions")
                    except Exception as e:
                        logger.error(f"Kafka topic creation failed: {e}")
                        context["error"] = f"Failed to create topic in Kafka: {str(e)}"
                        return render(request, "admin.html", context)
                    Topic.objects.create(
                        name=topic_name,
                        partitions=partitions,
                        created_by=request.user,
                        production="Active",
                        consumption="Active",
                        followers=1,
                        observers=0,
                        last_produced=timezone.now()
                    )
                    logger.info(f"Admin created topic '{topic_name}' in Django")
                    messages.success(request, f"Topic '{topic_name}' created successfully!")
                    return redirect("admin_dashboard")
            except ValueError:
                context["error"] = "Invalid number of partitions."
        else:
            context["error"] = "Please fill all fields."
    return render(request, "admin.html", context)

@csrf_exempt
def create_topic_api(request, request_id):
    """
    Allows a normal authenticated user to create a Kafka topic
    for their approved topic request.
    """
    if request.method != "POST":
        return JsonResponse(
            {"success": False, "message": "Invalid request method. Use POST."},
            status=400
        )

    user = request.user
    if not user.is_authenticated:
        return JsonResponse({"success": False, "message": "Unauthorized"}, status=401)

    try:
        # Only allow normal (non-admin) users
        if user.is_superuser:
            return JsonResponse({"success": False, "message": "Admins cannot use this endpoint."}, status=403)

        # Fetch approved request made by this user
        topic_request = TopicRequest.objects.get(
            id=request_id,
            requested_by=user,
            status='APPROVED'
        )

        topic_name = topic_request.topic_name
        partitions = topic_request.partitions

        #  Create Kafka topic
        admin_client = AdminClient({'bootstrap.servers': ','.join(KAFKA_BOOTSTRAP)})
        # admin_client = AdminClient(conf);

        new_topic = NewTopic(
            topic=topic_name,
            num_partitions=partitions,
            replication_factor=1
        )

        try:
            fs = admin_client.create_topics([new_topic])
            for topic, f in fs.items():
                f.result()  # will raise exception if Kafka fails

        except Exception as kafka_error:
            logger.error(f"[{user.username}] Kafka topic creation error: {kafka_error}")
            return JsonResponse(
                {"success": False, "message": f"Kafka error: {kafka_error}"},
                status=500
            )

        # Save to DB
        Topic.objects.create(
            name=topic_name,
            partitions=partitions,
            created_by=user,
            production="Active",
            consumption="Active",
            followers=1,
            observers=0,
            last_produced=timezone.now()
        )

        # Update request status
        topic_request.status = 'PROCESSED'
        topic_request.save()

        return JsonResponse(
            {"success": True, "message": f"Topic '{topic_name}' created successfully."}
        )

    except TopicRequest.DoesNotExist:
        return JsonResponse(
            {"success": False, "message": "Approved request not found or unauthorized."},
            status=404
        )

    except Exception as e:
        logger.error(f"[{user.username}] Unexpected error: {e}")
        return JsonResponse(
            {"success": False, "message": f"Unexpected error: {str(e)}"},
            status=500
        )

@login_required
def create_topic_form(request, request_id):
    try:
        topic_request = TopicRequest.objects.get(id=request_id, requested_by=request.user, status='APPROVED')
        highlight = request.GET.get('highlight', '')
        context = {
            "topic_name": topic_request.topic_name,
            "partitions": topic_request.partitions,
            "username": request.user.username,
            "topics": Topic.objects.filter(created_by=request.user, is_active=True),
            "request_id": request_id,
            "highlight": highlight
        }
        if request.method == "GET":
            return render(request, "create_topic.html", context)
        elif request.method == "POST":
            return create_topic(request)
    except TopicRequest.DoesNotExist:
        return render(request, "home.html", {
            "topics": Topic.objects.filter(is_active=True, created_by=request.user),
            "username": request.user.username,
            "error": "Approved request not found or you don't have permission."
        })
                         
@csrf_exempt
def create_topic(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if request.method == "POST":
        topic_name = request.POST.get("topic_name").strip()
        partitions = request.POST.get("partitions")
        request_id = request.POST.get("request_id")
        if topic_name and partitions:
            try:
                partitions = int(partitions)
                if partitions < 1:
                    return render(request, "create_topic.html", {
                        "topic_name": topic_name,
                        "partitions": partitions,
                        "username": request.user.username,
                        "topics": Topic.objects.filter(created_by=request.user, is_active=True),
                        "error": "Partitions must be at least 1."
                    })
                if not re.match(r'^[a-zA-Z0-9._-]+$', topic_name):
                    return render(request, "create_topic.html", {
                        "topic_name": topic_name,
                        "partitions": partitions,
                        "username": request.user.username,
                        "topics": Topic.objects.filter(created_by=request.user, is_active=True),
                        "error": "Topic name can only contain letters, numbers, dots, underscores, and hyphens."
                    })
                if not request.user.is_superuser:
                    approved_request = TopicRequest.objects.filter(
                        requested_by=request.user,
                        topic_name=topic_name,
                        status='APPROVED'
                    ).first()
                    if not approved_request:
                        return render(request, "home.html", {
                            "topics": Topic.objects.filter(is_active=True, created_by=request.user),
                            "username": request.user.username,
                            "error": "You need superuser approval to create this topic."
                        })
                # Check for existing topic and handle accordingly
                existing_topic = Topic.objects.filter(name=topic_name, is_active=True).first()
                if existing_topic:
                    if approved_request:
                        approved_request.status = 'PROCESSED'
                        approved_request.save()
                        logger.info(f"Request for '{topic_name}' marked as PROCESSED due to existing topic")
                    messages.warning(request, f"Topic '{topic_name}' already exists. Request marked as processed.")
                    return redirect("home")
                try:
                    admin_client = AdminClient({
                        'bootstrap.servers': ','.join(KAFKA_BOOTSTRAP)
                    })
                    # admin_client = AdminClient(conf);
                    new_topic = NewTopic(topic_name, num_partitions=partitions, replication_factor=1)
                    admin_client.create_topics([new_topic])
                    logger.info(f"Kafka topic '{topic_name}' created with {partitions} partitions")
                except Exception as e:
                    logger.error(f"Kafka topic creation failed: {e}")
                    return render(request, "create_topic.html", {
                        "topic_name": topic_name,
                        "partitions": partitions,
                        "username": request.user.username,
                        "topics": Topic.objects.filter(created_by=request.user, is_active=True),
                        "error": f"Failed to create topic in Kafka: {str(e)}"
                    })
                Topic.objects.create(
                    name=topic_name,
                    partitions=partitions,
                    created_by=request.user,
                    production="Active",
                    consumption="Active",
                    followers=1,
                    observers=0,
                    last_produced=timezone.now()
                )
                if approved_request:
                    approved_request.status = 'PROCESSED'
                    approved_request.save()
                    logger.info(f"Request for '{topic_name}' marked as PROCESSED after creation")
                logger.info(f"Created topic '{topic_name}' in Django by {request.user.username}")
                messages.success(request, f"Topic '{topic_name}' created successfully!")
                return redirect("home")
            except ValueError:
                return render(request, "create_topic.html", {
                    "topic_name": topic_name,
                    "partitions": partitions,
                    "username": request.user.username,
                    "topics": Topic.objects.filter(created_by=request.user, is_active=True),
                    "error": "Invalid number of partitions."
                })
        return render(request, "create_topic.html", {
            "topic_name": topic_name,
            "partitions": partitions,
            "username": request.user.username,
            "topics": Topic.objects.filter(created_by=request.user, is_active=True),
            "error": "Please fill all fields."
        })
    return redirect("home")

@csrf_exempt
def alter_topic_partitions(request, topic_id):
    if request.method != "PATCH":
        return JsonResponse({"success": False, "message": "Invalid request method. Use PATCH."})

    try:
        topic = Topic.objects.get(id=topic_id)
        data = json.loads(request.body.decode("utf-8"))
        new_partition_count = data.get("new_partition_count")

        if not new_partition_count or not isinstance(new_partition_count, int):
            return JsonResponse({"success": False, "message": "Provide a valid integer for new_partition_count."})

        # Connect to Kafka
        admin_client = AdminClient({
            'bootstrap.servers': ','.join(KAFKA_BOOTSTRAP)
        })
        # admin_client = AdminClient(conf);
        # Get current partitions from Kafka
        metadata = admin_client.list_topics(timeout=10)
        current_partitions = len(metadata.topics[topic.name].partitions)

        logger.info(f"Current partitions for '{topic.name}': {current_partitions}")

        if new_partition_count <= current_partitions:
            return JsonResponse({
                "success": False,
                "message": f"Cannot reduce partitions. Current: {current_partitions}, Requested: {new_partition_count}"
            })

        new_parts = [
             NewPartitions(topic=topic.name, new_total_count=new_partition_count)
        ]
        fs = admin_client.create_partitions(new_parts)

        for t, f in fs.items():
            try:
                f.result()  # Wait for operation completion
                logger.info(f"Topic '{t}' partition count increased to {new_partition_count}.")
            except Exception as e:
                logger.error(f"Failed to alter partitions for {t}: {e}")
                return JsonResponse({"success": False, "message": f"Kafka alter failed: {str(e)}"})

        # Update in database
        topic.partitions = new_partition_count
        topic.save()

        return JsonResponse({
            "success": True,
            "message": f"Partitions for topic '{topic.name}' increased from {current_partitions} → {new_partition_count}"
        })

    except Topic.DoesNotExist:
        return JsonResponse({"success": False, "message": "Topic not found."})
    except Exception as e:
        import traceback
        logger.error(traceback.format_exc())
        return JsonResponse({"success": False, "message": str(e)})

@csrf_exempt
def delete_topic_api(request, topic_id):
    if request.method != "DELETE":
        return JsonResponse({"success": False, "message": "Invalid request method."})

    try:
        topic = Topic.objects.get(id=topic_id)
        logger.info(f"Received DELETE request for topic: {topic.name}")

        admin_client = AdminClient({
            'bootstrap.servers': ','.join(KAFKA_BOOTSTRAP)
        })
        # admin_client = AdminClient(conf);
        # Delete topic in Kafka
        fs = admin_client.delete_topics([topic.name], operation_timeout=30)
        for topic_name, f in fs.items():
            try:
                f.result()  # Wait for operation to complete
                logger.info(f"Kafka topic '{topic_name}' deleted successfully.")
            except Exception as e:
                logger.error(f"Kafka topic deletion failed: {e}")
                return JsonResponse({"success": False, "message": f"Kafka deletion failed: {str(e)}"})

        # Delete from DB
        topic.delete()
        logger.info(f"Topic '{topic.name}' deleted successfully from Django DB.")
        return JsonResponse({"success": True, "message": f"Topic '{topic.name}' deleted successfully!"})

    except Topic.DoesNotExist:
        return JsonResponse({"success": False, "message": "Topic not found."})
    except Exception as e:
        logger.error(f"Error deleting topic: {e}")
        return JsonResponse({"success": False, "message": str(e)})

@csrf_exempt
def delete_topic(request):
    if request.method == "POST":
        topic_ids = request.POST.getlist("topic_ids")
        if not topic_ids:
            messages.error(request, "No topics selected for deletion.")
            return render(request, "create_topic.html", {
                "username": request.user.username,
                "topics": Topic.objects.filter(created_by=request.user, is_active=True)
            })
        try:
            admin_client = AdminClient({
                'bootstrap.servers': ','.join(KAFKA_BOOTSTRAP)
            })
            # admin_client = AdminClient(conf)
            for topic_id in topic_ids:
                topic = Topic.objects.get(id=topic_id, created_by=request.user, is_active=True)
                try:
                    admin_client.delete_topics([topic.name])
                    logger.info(f"Kafka topic '{topic.name}' deleted by {request.user.username}")
                except Exception as e:
                    logger.error(f"Kafka topic deletion failed: {e}")
                    messages.error(request, f"Failed to delete topic '{topic.name}' from Kafka: {str(e)}")
                    continue
                topic.delete()  # Permanent deletion
                logger.info(f"Topic '{topic.name}' permanently deleted in Django by {request.user.username}")
            messages.success(request, "Selected topics deleted successfully!")
            return redirect("home" if not request.user.is_superuser else "admin_dashboard")
        except Topic.DoesNotExist:
            messages.error(request, "One or more selected topics not found or you don't have permission.")
            return render(request, "create_topic.html", {
                "username": request.user.username,
                "topics": Topic.objects.filter(created_by=request.user, is_active=True)
            })
    return JsonResponse({"success": False, "message": "Invalid request"})

@login_required
def topic_detail(request, topic_name):
    try:
        topic = Topic.objects.get(name=topic_name, is_active=True, created_by=request.user)
        topic_request = TopicRequest.objects.filter(
            topic_name=topic_name,
            requested_by=request.user,
            status='APPROVED'
        ).order_by('-reviewed_at').first()
        request_id = topic_request.id if topic_request else None
        context = {
            "topic": topic,
            "username": request.user.username,
            "topics": Topic.objects.filter(created_by=request.user, is_active=True),
            "request_id": request_id
        }
        return render(request, "topic_detail.html", context)
    except Topic.DoesNotExist:
        return render(request, "topic_detail.html", {
            "topics": Topic.objects.filter(is_active=True, created_by=request.user),
            "username": request.user.username,
            "error": f"Topic {topic_name} does not exist or you don't have permission."
        })

def execute_confluent_command(command, topic_name=None, partitions=None):
    return False, "This is a placeholder function for confluent command"

@csrf_exempt
def topic_detail_api(request, topic_name):
    try:
        topic = Topic.objects.get(name=topic_name, is_active=True)
        data = {
            "id": topic.id,
            "name": topic.name,
            "partitions": topic.partitions,
            "created_by": topic.created_by.username,
            "production": topic.production,
            "consumption": topic.consumption,
            "followers": topic.followers,
            "observers": topic.observers,
            "last_produced": topic.last_produced,
        }
        return JsonResponse({"success": True, "topic": data})
    except Topic.DoesNotExist:
        return JsonResponse({"success": False, "message": "Topic not found"}, status=404)

# @login_required
# def create_partition(request, topic_name):
#     if not request.user.is_authenticated:
#         return redirect("login")
#     if request.method == "POST":
#         partitions_to_delete = request.POST.get("partitions")
#         if partitions_to_delete:
#             try:
#                 partitions_to_delete = int(partitions_to_delete)
#                 if partitions_to_delete < 1:
#                     return render(request, "topic_detail.html", {
#                         "topic": Topic.objects.get(name=topic_name, is_active=True, created_by=request.user),
#                         "username": request.user.username,
#                         "topics": Topic.objects.filter(created_by=request.user, is_active=True),
#                         "error": "Partitions must be at least 1."
#                     })
#                 topic = Topic.objects.get(name=topic_name, is_active=True, created_by=request.user)
#                 if partitions_to_delete >= topic.partitions:
#                     return render(request, "topic_detail.html", {
#                         "topic": topic,
#                         "username": request.user.username,
#                         "topics": Topic.objects.filter(created_by=request.user, is_active=True),
#                         "error": "Cannot delete more partitions than exist."
#                     })
#                 if topic.created_by != request.user and not request.user.is_superuser:
#                     return render(request, "topic_detail.html", {
#                         "topic": topic,
#                         "username": request.user.username,
#                         "topics": Topic.objects.filter(created_by=request.user, is_active=True),
#                         "error": "You can only delete partitions from topics you created."
#                     })
#                 success, message = execute_confluent_command("delete_partition", topic_name, partitions_to_delete)
#                 if success:
#                     topic.partitions -= partitions_to_delete
#                     if topic.partitions <= 0:
#                         topic.delete()  # Permanently delete topic if no partitions remain
#                         logger.info(f"Topic '{topic_name}' permanently deleted due to no partitions by {request.user.username}")
#                     else:
#                         topic.save()
#                         LogEntry.objects.create(
#                             command=f"delete_partition_{topic_name}",
#                             approved=True,
#                             message=f"Permanently deleted {partitions_to_delete} partitions from {topic_name} by {request.user.username}"
#                         )
#                         logger.info(f"Permanently deleted {partitions_to_delete} partitions from {topic_name} by {request.user.username}")
#                     return redirect("home" if not request.user.is_superuser else "admin_dashboard")
#                 else:
#                     return render(request, "topic_detail.html", {
#                         "topic": topic,
#                         "username": request.user.username,
#                         "topics": Topic.objects.filter(created_by=request.user, is_active=True),
#                         "error": message
#                     })
#             except ValueError:
#                 return render(request, "topic_detail.html", {
#                     "topic": Topic.objects.get(name=topic_name, is_active=True, created_by=request.user),
#                     "username": request.user.username,
#                     "topics": Topic.objects.filter(created_by=request.user, is_active=True),
#                     "error": "Invalid number of partitions."
#                 })
#             except Topic.DoesNotExist:
#                 return render(request, "topic_detail.html", {
#                     "topics": Topic.objects.filter(is_active=True, created_by=request.user),
#                     "username": request.user.username,
#                     "error": f"Topic {topic_name} does not exist or you don't have permission."
#                 })
#         return render(request, "topic_detail.html", {
#             "topic": Topic.objects.get(name=topic_name, is_active=True, created_by=request.user),
#             "username": request.user.username,
#             "topics": Topic.objects.filter(created_by=request.user, is_active=True),
#             "error": "Please specify the number of partitions."
#         })
#     return redirect("home" if not request.user.is_superuser else "admin_dashboard")

@login_required
def delete_partition(request, topic_name):
    # Redirect to topic_detail for consistency, where deletion is handled
    return redirect("topic_detail", topic_name=topic_name)

@login_required
def submit_request(request):
    if request.method == "POST":
        topic_name = request.POST.get("topic_name")
        partitions = request.POST.get("partitions")
        if topic_name and partitions:
            try:
                partitions = int(partitions)
                if partitions < 1:
                    return JsonResponse({"success": False, "message": "Partitions must be at least 1."})
                TopicRequest.objects.create(
                    topic_name=topic_name,
                    partitions=partitions,
                    requested_by=request.user
                )
                logger.info(f"Topic request for {topic_name} submitted by {request.user.username}")
                return JsonResponse({"success": True, "message": "Topic creation request submitted"})
            except ValueError:
                return JsonResponse({"success": False, "message": "Invalid number of partitions."})
        return JsonResponse({"success": False, "message": "Please fill all fields."})
    return JsonResponse({"success": False, "message": "Invalid request"})

@csrf_exempt
def approve_request(request, request_id):
    if not request.user.is_authenticated or not request.user.is_superuser:
        return redirect("home")
    if request.method == "POST":
        try:
            topic_request = TopicRequest.objects.get(id=request_id, status='PENDING')
            topic_request.status = 'APPROVED'
            topic_request.reviewed_by = request.user
            topic_request.reviewed_at = timezone.now()
            topic_request.save()
            logger.info(f"Request {request_id} approved by {request.user.username}")
            messages.success(request, f"Request for '{topic_request.topic_name}' approved!")
        except TopicRequest.DoesNotExist:
            messages.error(request, "Request not found or already processed.")
        return redirect("admin_dashboard")
    return redirect("admin_dashboard")

@csrf_exempt
def decline_request(request, request_id):
    if not request.user.is_authenticated or not request.user.is_superuser:
        return redirect("home")
    if request.method == "POST":
        try:
            topic_request = TopicRequest.objects.get(id=request_id, status='PENDING')
            topic_request.status = 'DECLINED'
            topic_request.reviewed_by = request.user
            topic_request.reviewed_at = timezone.now()
            topic_request.save()
            logger.info(f"Request {request_id} declined by {request.user.username}")
            messages.success(request, f"Request for '{topic_request.topic_name}' declined.")
        except TopicRequest.DoesNotExist:
            messages.error(request, "Request not found or already processed.")
        return redirect("admin_dashboard")
    return redirect("admin_dashboard")