# SATYAMEBA single-user server config (baked into the notebook image).
#
# Enables JupyterLab's supported custom-CSS feature so our neon theme loads from
# {config_dir}/custom/custom.css. The satyameba_traffic server extension enables
# itself additively via etc/jupyter/jupyter_server_config.d (installed by its
# wheel), so we deliberately do NOT set jpserver_extensions here (that would
# clobber other extensions like nvdashboard / resource-usage).
c = get_config()  # noqa: F821

c.LabApp.custom_css = True
