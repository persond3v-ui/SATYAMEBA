# SATYAMEBA single-user notebook image (the sandbox each user actually runs in).
#
# Base: CUDA-enabled scientific Python stick. For pure-CPU clusters you can swap
# the FROM line for quay.io/jupyter/scipy-notebook:latest and drop the CUDA bits.
FROM quay.io/jupyter/scipy-notebook:2024-06-17

USER root

# Common ML/data libraries pre-baked so notebooks start fast. GPU wheels are
# pulled at build time only when SAT_GPU_BUILD=true (see build arg).
ARG SAT_GPU_BUILD=false
RUN pip install --no-cache-dir \
        pandas numpy scipy matplotlib seaborn scikit-learn \
        ipywidgets jupyterlab plotly && \
    if [ "$SAT_GPU_BUILD" = "true" ]; then \
        pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu121 ; \
    fi

# Harden the sandbox: notebooks run as the unprivileged jovyan user with no
# sudo. The container itself is started with cap_drop=ALL + no-new-privileges
# by the spawner.
USER ${NB_UID}
WORKDIR /home/jovyan/work
