from secrets import token_hex

from kubespawner_keycloak import KubespawnerKeycloak, VolumeManager
from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import V1Pod, V1ObjectMeta
from kubespawner.utils import get_k8s_model
from kubespawner import KubeSpawner
import os
import z2jh

async def modify_pod_hook(spawner: KubeSpawner, pod: V1Pod):
    # Add additional storage based on workspace label on pod
    # This ensures that the correct storage is mounted into the correct workspace
    
    try:
        metadata: V1ObjectMeta = pod.metadata
        spawner.log.info(f"Attempting to mount storage for pod {metadata.name} on {metadata.namespace}")

        namespace = os.environ.get("POD_NAMESPACE", "default")
        workspace = metadata.labels.get("workspace", "")
        volume_manager : VolumeManager = VolumeManager(spawner, k8s_api)

        if workspace:
            # Remove other user storage if workspace has dedicated storage specified
            # This prevents user from moving data between workspaces using their personal
            # storage that appears in all workpaces.
            # Unless the user is an admin user, in which case leave their storage in place

            admin_users = z2jh.get_config(
                "hub.config.AzureAdOAuthenticator.admin_users", []
            )

            if spawner.user.name not in admin_users:
                pod.spec.volumes = []
                pod.spec.containers[0].volume_mounts = []

            await volume_manager.mount_volume(pod, workspace, namespace)        
        await volume_manager.mount_volume(pod, "shared", namespace, read_only=True)

    except Exception as e:
        spawner.log.error(f"Error mounting storage! Error msg {str(e)}")

    return pod

def userdata_hook(spawner, auth_state):
    spawner.oauth_user = auth_state["oauth_user"]
    spawner.access_token = auth_state["access_token"]

def get_workspaces(spawner: KubeSpawner):
    base_url = z2jh.get_config("hub.config.GenericOAuthenticator.keycloak_api_base_url")
    keycloak = KubespawnerKeycloak(spawner = spawner, base_url = base_url, access_token = spawner.access_token, environments_config = z2jh.get_config("custom.environments"))
    return keycloak.get_permitted_workspaces()

config.load_incluster_config()
k8s_api = client.ApiClient() 
c.KubeSpawner.start_timeout = 900
c.JupyterHub.authenticator_class = 'oauthenticator.generic.GenericOAuthenticator'
c.GenericOAuthenticator.enable_auth_state = True
os.environ['JUPYTERHUB_CRYPT_KEY'] = token_hex(32)

c.Spawner.auth_state_hook = userdata_hook
c.KubeSpawner.modify_pod_hook = modify_pod_hook
c.KubeSpawner.profile_list = get_workspaces
c.KubeSpawner.profile_form_template = """
        <style>
        /* The profile description should not be bold, even though it is inside the <label> tag */
        #kubespawner-profiles-list label p {
            font-weight: normal;
        }
        </style>
        <div class='form-group' id='kubespawner-profiles-list'>
        {% for profile in profile_list %}
        <label for='profile-item-{{ profile.slug }}' class='form-control input-group'>
            <div class='col-md-1'>
                <input type='radio' name='profile' id='profile-item-{{ profile.slug }}' value='{{ profile.slug }}' {% if profile.default %}checked{% endif %} />
            </div>
            <div class='col-md-11'>
                <strong>{{ profile.display_name }}</strong>
                {% if profile.description %}
                    <p>{{ profile.description }}
                {% endif %}
                {% if profile.kubespawner_override.image %}
                    <br><em>Image: {{ profile.kubespawner_override.image.split('/')[-1] }}</em>
                {% endif %}
                <br><em>Your access expires in : {{profile.user_ws_days_left }} days.</em>
                </p>
            </div>
        </label>
        {% endfor %}
        </div>
        """
