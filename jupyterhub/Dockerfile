# SATYAMEBA JupyterHub image
FROM quay.io/jupyterhub/jupyterhub:4.1

RUN pip install --no-cache-dir \
        dockerspawner==13.0.0 \
        jupyterhub-idle-culler==1.3.1 \
        tornado

COPY satyameba_authenticator.py /srv/jupyterhub/satyameba_authenticator.py
COPY jupyterhub_config.py /srv/jupyterhub/jupyterhub_config.py

ENV PYTHONPATH=/srv/jupyterhub
WORKDIR /srv/jupyterhub

EXPOSE 8000 8081
CMD ["jupyterhub", "-f", "/srv/jupyterhub/jupyterhub_config.py"]
