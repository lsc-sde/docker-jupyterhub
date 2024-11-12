---
title: Jupyter Hub Image
parent: Jupyter Hub
grand_parent: Dynamic Compute Resource
layout: page
---

This is a customised version of the Jupyter Hub image.

## Inheritance
This container image inherits from the **quay.io/jupyterhub/k8s-hub:3.2.1** image and extends it to include the [Analytics Workspace Management Libraries integrated](https://github.com/lsc-sde/py-lscsde-workspace-mgmt).

## Extension
The following files are updated:

### custom_templates
These custom templates change how screens are displayed to the user

| File | Description |
| --- | --- | 
| form.html | Customises how the form is rendered for users to select a workspace or image |
| page.html | Customises the overall layout and design for the jupyter hub home page |
| spawn.html | Customises the layout for the spawner page |

### jupyterhub_config.d
This folder customises the python executed by jupyterhub to include our changes for jupyter hubs logic.

#### WorkspaceManager Class
The new workspace manager class is introduced to make it easier to manage interactions with the customised logic of jupyter.

This allows us to choose a number of different paths depending on what feature flags are activated on the environmental variables, changing the flow called by the solution while keeping it relatively the same.

TODO: This relates to some functionality and features which are supported by much older iterations of the solution but are not current. These should be reworked and removed.