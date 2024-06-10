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

    
    async def auth_state_hook(self, spawner : KubeSpawner, auth_state):
        spawner.log.info(f"Getting Auth State using manager: {self.name}")
        match workspace_manager.name:
            case "keycloak":
                self.keycloak_auth_state_hook(spawner, auth_state)

            case "lscsde":
                self.lscsde_auth_state_hook(spawner, auth_state)
            
    def keycloak_auth_state_hook(self, spawner : KubeSpawner, auth_state):
        spawner.log.info(f"Processing auth state for keycloak")
        spawner.oauth_user = auth_state["oauth_user"]
        spawner.access_token = auth_state["access_token"]

    def lscsde_auth_state_hook(self, spawner : KubeSpawner, auth_state):
        spawner.log.info(f"Processing auth state for lscsde")


    # Effective Feature Flag based on environmental variable, defaults to keycloak if not present
    async def get_workspaces(self, spawner : KubeSpawner):
        spawner.log.info(f"Getting workspaces using manager: {self.name}")
        workspaces = []
        match self.name:
            case "keycloak":
                workspaces = self.get_workspaces_keycloak(spawner)
            case "lscsde":
                workspaces = await self.get_workspaces_lscsde(spawner)  
            case _:
                spawner.log.error(f"{self.name} is not implemented")
        
        if len(workspaces) == 0:
            raise Exception(f"Could not find any permitted workspaces for user")
        
        for workspace in workspaces:
            mem_limit = workspace.get("kubespawner_override", {}).get("mem_limit", spawner.mem_limit)
            mem_guarantee = workspace.get("kubespawner_override", {}).get("mem_guarantee", spawner.mem_guarantee)
            cpu_limit = workspace.get("kubespawner_override", {}).get("cpu_limit", spawner.cpu_limit)
            cpu_guarantee = workspace.get("kubespawner_override", {}).get("cpu_guarantee", spawner.cpu_guarantee)

            if not mem_limit:
                mem_limit = 2147483648

            if not mem_guarantee:
                mem_limit = 1073741824

            if not cpu_limit:
                cpu_limit = 1

            if not cpu_guarantee:
                cpu_guarantee = 1

            workspace["kubespawner_override"]["mem_limit"] = mem_limit
            workspace["kubespawner_override"]["mem_guarantee"] = mem_guarantee
            workspace["kubespawner_override"]["cpu_limit"] = cpu_limit
            workspace["kubespawner_override"]["cpu_guarantee"] = cpu_guarantee

        return workspaces

    async def get_workspaces_lscsde(self, spawner: KubeSpawner):
        spawner.log.info(f"Groups = {spawner.user.groups}")
        username : str = spawner.user.name
        mgr = AnalyticsWorkspaceManager(api_client = api_client, log = spawner.log)
        spawner.log.info(f"Getting permitted workspaces for {username} from {self.namespace} namespace")
        return await mgr.get_permitted_workspaces(self.namespace, username)
    
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
        metadata : V1ObjectMeta = pod.metadata
        spawner.log.info(f"Modifying Pod {metadata.name} on {metadata.namespace} using manager: {self.name}")
        if not metadata.namespace:
            spawner.log.info(f"Setting Pod namespace to {self.namespace} on {metadata.name}")
            metadata.namespace = self.namespace
            
        match self.name:
            case "keycloak":
                return await self.modify_pod_hook_keycloak(spawner, pod)
            case "lscsde":
                return await self.modify_pod_hook_lscsde(spawner, pod) 
            case _:
                raise(Exception(f"{self.name} is not implemented"))   
             
    async def modify_pod_hook_lscsde(self, spawner: KubeSpawner, pod: V1Pod):
        # Add additional storage from keycloak configuration based on workspace label on pod
        # This ensures that the correct storage is mounted into the correct workspace
        mgr = AnalyticsWorkspaceManager(api_client = api_client, log = spawner.log)
        
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

                await mgr.mount_workspace(
                    pod = pod, 
                    storage_class_name = "jupyter-default",
                    mount_prefix = "/home/jovyan",
                    storage_prefix = "jupyter-"
                    )
                
            await mgr.pvc_client.mount(
                pod = pod,
                storage_name = "jupyter-shared",
                namespace = self.namespace,
                storage_class_name = "jupyter-default",
                mount_path = "/home/jovyan/shared",
                read_only = True
            )

            spawner.log.info(f"Pod Definition {pod}")

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


load_incluster_config()
api_client = ApiClient() 
workspace_manager = WorkspaceManager(api_client = api_client)
c.KubeSpawner.start_timeout = 900
crypt_key = os.environ.get('JUPYTERHUB_CRYPT_KEY') 
if not crypt_key:
    crypt_key = token_hex(32)
    os.environ.setdefault('JUPYTERHUB_CRYPT_KEY', crypt_key)

c.Spawner.auth_state_hook = workspace_manager.auth_state_hook
c.KubeSpawner.modify_pod_hook = workspace_manager.modify_pod_hook
c.KubeSpawner.profile_list = workspace_manager.get_workspaces
c.KubeSpawner.profile_form_template = """
        <style>
        .workspace {
            font-weight: normal;
        }

        .workspace_name {
            font-weight: bold;
        }

        .workspace_header {
            font-style: italic;  
            font-weight: bold;          
        }

        .workspace_subheader {
            font-style: italic;  
        }

        .workspace_details {
            margin-top: 10px;
            font-size: 0.9em;
        }

        .workspace_resources {
            margin-top: 10px;
            font-size: 0.9em;
        }

        </style>
        <div class='form-group' id='kubespawner-profiles-list'>
        {% for profile in profile_list %}
        <label for='profile-item-{{ profile.slug }}' class='form-control input-group'>
            <div class='col-md-1'>
                <input type='radio' name='profile' id='profile-item-{{ profile.slug }}' value='{{ profile.slug }}' {% if profile.default %}checked{% endif %} />
            </div>
            <div class='col-md-11 workspace'>
                <div>
                    <div class='row'>
                        <div class='col-md-11'>
                            <div class='workspace_name'>{{ profile.display_name }}</div>
                            {% if profile.description %}
                                <div class='workspace_description'>{{ profile.description }}</div>
                            {% endif %}
                        </div>
                    </div>
                    <div class='row workspace_details'>
                        <div class='col-md-6'>
                            {% if profile.kubespawner_override.image %}
                                <div class='workspace_header'>
                                    Image:
                                </div>
                                <div class='workspace_image'>
                                    {{ profile.kubespawner_override.image.split('/')[-1] }}
                                </div>
                            {% endif %}
                        </div>
                        <div class='col-md-6'>
                            <div class='workspace_header'>
                                Access expires in:
                            </div>
                            <div class='workspace_expiry'>
                                {{profile.ws_days_left.days }} days.
                            </div>
                        </div>
                    </div>
                    <div class='row workspace_resources'>
                        <div class='col-md-6'>
                            <div class='workspace_header'>
                                Memory:
                            </div>
                            <div class='col-md-6'>
                                <div class='workspace_subheader'>
                                    Guaranteed:
                                </div>
                                <div> 
                                    {% if profile.kubespawner_override %}
                                        {% if profile.kubespawner_override.mem_guarantee %}
                                            {{profile.kubespawner_override.mem_guarantee / 1024 / 1024 / 1024 }}Gi
                                        {% endif %}
                                    {% endif %} &nbsp;
                                </div>
                            </div>
                            <div class='col-md-6'>
                                <div class='workspace_subheader'>
                                    Limit:
                                </div>
                                <div> 
                                    {% if profile.kubespawner_override %}
                                        {% if profile.kubespawner_override.mem_limit %}
                                            {{profile.kubespawner_override.mem_limit / 1024 / 1024 / 1024}}Gi
                                        {% endif %}
                                    {% endif %} &nbsp;
                                </div>
                            </div>
                        </div>
                        <div class='col-md-6'>
                            <div class='workspace_header'>
                                CPU:
                            </div>
                            <div class='col-md-6'>
                                <div class='workspace_subheader'>
                                    Guaranteed:
                                </div>
                                <div> 
                                    {% if profile.kubespawner_override %}
                                        {% if profile.kubespawner_override.cpu_guarantee %}
                                            {{profile.kubespawner_override.cpu_guarantee}}
                                        {% endif %}
                                    {% endif %} &nbsp;
                                </div>
                            </div>
                            <div class='col-md-6'>
                                <div class='workspace_subheader'>
                                    Limit:
                                </div>
                                <div> 
                                    {% if profile.kubespawner_override %}
                                        {% if profile.kubespawner_override.cpu_limit %}
                                            {{profile.kubespawner_override.cpu_limit}}
                                        {% endif %}
                                    {% endif %} &nbsp;
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </label>
        {% endfor %}
        </div>
        """
