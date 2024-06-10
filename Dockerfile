FROM quay.io/jupyterhub/k8s-hub:3.2.1

RUN pip install --upgrade pip
RUN pip install kubespawner-keycloak==0.1.4
RUN pip install lscsde-workspace-mgmt==0.1.5

COPY ./jupyterhub_config.d/jupyterhub_custom_config.py /usr/local/etc/jupyterhub/jupyterhub_config.d/jupyterhub_config_custom.py
COPY ./custom_templates/page.html /usr/local/etc/jupyterhub/custom_templates/page.html
COPY ./custom_templates/spawn.html /usr/local/etc/jupyterhub/custom_templates/spawn.html

ENV WORKSPACE_MANAGER=lscsde