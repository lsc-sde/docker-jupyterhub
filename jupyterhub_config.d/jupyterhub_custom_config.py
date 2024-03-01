from secrets import token_hex

from kubespawner_keycloak import KubespawnerKeycloak, VolumeManager
from kubernetes_asyncio.client import V1Pod, V1ObjectMeta, ApiClient
from kubernetes_asyncio.config import load_incluster_config
from kubespawner.utils import get_k8s_model
from kubespawner import KubeSpawner
from lscsde_workspace_mgmt import AnalyticsWorkspaceManager
from lscsde_workspace_mgmt.managers import PersistentVolumeClaimClient
import os
import z2jh

class WorkspaceManager:
    def __init__(self, api_client : ApiClient):
        self.name : str = os.environ.get("WORKSPACE_MANAGER", "keycloak").casefold()
        self.namespace = os.environ.get("POD_NAMESPACE", "default")
        self.keycloak_base_url = z2jh.get_config("hub.config.GenericOAuthenticator.keycloak_api_base_url")
        self.keycloak_token_url = z2jh.get_config("hub.config.GenericOAuthenticator.keycloak_token_url")
        self.keycloak_client_id = z2jh.get_config("hub.config.GenericOAuthenticator.client_id")
        self.keycloak_client_secret = z2jh.get_config("hub.config.GenericOAuthenticator.client_secret")
        self.keycloak_environments = z2jh.get_config("custom.environments")
        self.lscsde_workspace_manager : AnalyticsWorkspaceManager = None
        match self.name:
            case "lscsde":
                self.lscsde_workspace_manager = AnalyticsWorkspaceManager(api_client = api_client)

    # Effective Feature Flag based on environmental variable, defaults to keycloak if not present
    async def get_workspaces(self, spawner : KubeSpawner):
        match self.name:
            case "keycloak":
                self.get_workspaces_keycloak(spawner)
            case "lscsde":
                await self.get_workspaces_lscsde(spawner)         
    
    async def get_workspaces_lscsde(self, spawner: KubeSpawner):
        username : str = spawner.user.name
        return await self.lscsde_workspace_manager.get_permitted_workspaces(self.namespace, username)
    
    def get_workspaces_keycloak(self, spawner: KubeSpawner):
        keycloak = KubespawnerKeycloak(
            spawner = spawner, 
            base_url = self.keycloak_base_url, 
            token_url = self.keycloak_token_url, 
            client_id = self.keycloak_client_id, 
            client_secret= self.keycloak_client_secret , 
            environments_config = self.keycloak_environments
            )
        return keycloak.get_permitted_workspaces()

    async def modify_pod_hook(self, spawner: KubeSpawner, pod : V1Pod):
        match self.name:
            case "keycloak":
                await self.modify_pod_hook_keycloak(spawner)
            case "lscsde":
                await self.modify_pod_hook_lscsde(spawner) 

    async def modify_pod_hook_lscsde(self, spawner: KubeSpawner, pod: V1Pod):
        # Add additional storage from keycloak configuration based on workspace label on pod
        # This ensures that the correct storage is mounted into the correct workspace
        
        try:
            metadata: V1ObjectMeta = pod.metadata
            spawner.log.info(f"Attempting to mount storage for pod {metadata.name} on {metadata.namespace}")
                        
            workspace = metadata.labels.get("workspace", "")
            
            if workspace:
                # Remove other user storage if workspace has dedicated storage specified
                # This prevents user from moving data between workspaces using their personal
                # storage that appears in all workpaces.
                # Unless the user is an admin user, in which case leave their storage in place

                pod.spec.volumes = []
                pod.spec.containers[0].volume_mounts = []

                await self.lscsde_workspace_manager.mount_workspace(
                    pod = pod, 
                    storage_class_name = "jupyter-storage",
                    mount_prefix = "/home/jovyan",
                    storage_prefix = "jupyter-"
                    )
            await self.lscsde_workspace_manager.pvc_client.mount(
                pod = pod,
                storage_name = "shared",
                namespace = self.namespace,
                storage_class_name = "jupyter-storage",
                mount_path = "/home/jovyan/shared",
                read_only = True
            )

        except Exception as e:
            spawner.log.error(f"Error mounting storage! Error msg {str(e)}")

        return pod     

    async def modify_pod_hook_keycloak(self, spawner: KubeSpawner, pod: V1Pod):
        # Add additional storage from keycloak configuration based on workspace label on pod
        # This ensures that the correct storage is mounted into the correct workspace
        
        try:
            metadata: V1ObjectMeta = pod.metadata
            spawner.log.info(f"Attempting to mount storage for pod {metadata.name} on {metadata.namespace}")

            workspace = metadata.labels.get("workspace", "")
            volume_manager = VolumeManager(spawner, api_client)

            if workspace:
                # Remove other user storage if workspace has dedicated storage specified
                # This prevents user from moving data between workspaces using their personal
                # storage that appears in all workpaces.
                # Unless the user is an admin user, in which case leave their storage in place

                pod.spec.volumes = []
                pod.spec.containers[0].volume_mounts = []

                await volume_manager.mount_volume(pod, workspace, self.namespace)        
            await volume_manager.mount_volume(pod, "shared", self.namespace, read_only=True)

        except Exception as e:
            spawner.log.error(f"Error mounting storage! Error msg {str(e)}")

        return pod

def userdata_hook(spawner, auth_state):
    spawner.oauth_user = auth_state["oauth_user"]
    spawner.access_token = auth_state["access_token"]

load_incluster_config()
api_client = ApiClient() 
workspace_manager = WorkspaceManager(api_client = api_client)
c.KubeSpawner.start_timeout = 900
c.JupyterHub.authenticator_class = 'oauthenticator.generic.GenericOAuthenticator'
c.GenericOAuthenticator.enable_auth_state = True
os.environ['JUPYTERHUB_CRYPT_KEY'] = token_hex(32)

c.Spawner.auth_state_hook = userdata_hook
c.KubeSpawner.modify_pod_hook = workspace_manager.modify_pod_hook
c.KubeSpawner.profile_list = workspace_manager.get_workspaces
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
