# SATYAMEBA single-user notebook image (the sandbox each user actually runs in).
#
# Base: CUDA-enabled scientific Python stack. For pure-CPU clusters you can swap
# the FROM line for quay.io/jupyter/scipy-notebook:latest and drop the CUDA bits.
FROM quay.io/jupyter/scipy-notebook:2024-06-17

USER root

# Common ML/data libraries pre-baked so notebooks start fast. GPU wheels are
# pulled at build time only when SAT_GPU_BUILD=true (see build arg).
ARG SAT_GPU_BUILD=false
RUN pip install --no-cache-dir \
        pandas numpy scipy matplotlib seaborn scikit-learn \
        ipywidgets jupyterlab plotly \
        jupyter-resource-usage jupyterlab-nvdashboard && \
    if [ "$SAT_GPU_BUILD" = "true" ]; then \
        pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu121 ; \
    fi

# --- SATYAMEBA notebook experience -----------------------------------------
# Neon theme (loaded via JupyterLab's custom-CSS feature), the in-notebook
# traffic widget (a pure-Python server extension — no front-end build, so the
# image build can never fail on it), and the distributed-training launcher.
COPY custom/custom.css         /etc/jupyter/custom/custom.css
COPY jupyter_server_config.py  /etc/jupyter/jupyter_server_config.py
COPY satyameba_traffic_pkg     /opt/satyameba/satyameba_traffic_pkg
COPY satyameba-ddp             /usr/local/bin/satyameba-ddp

RUN pip install --no-cache-dir /opt/satyameba/satyameba_traffic_pkg && \
    (jupyter server extension enable satyameba_traffic --sys-prefix || true) && \
    chmod +x /usr/local/bin/satyameba-ddp

# Harden the sandbox: notebooks run as the unprivileged jovyan user with no
# sudo. The container itself is started with cap_drop=ALL + no-new-privileges
# by the spawner.
USER ${NB_UID}
WORKDIR /home/jovyan/work
