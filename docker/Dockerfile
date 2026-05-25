FROM python:3.12-slim


WORKDIR /code


COPY ./code/requirements.txt /code/requirements.txt


RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt


COPY ./code/app /code/app


# CMD ["fastapi", "run", "app/main.py", "--port", "8000"]

# If you are running your container behind a TLS Termination Proxy (load balancer)
# CMD ["fastapi", "run", "app/main.py", "--proxy-headers", "--port", "8000"]