FROM python:3.13
WORKDIR /code

COPY ./requirements.txt ./code/
COPY ./commandline.py ./code/
COPY ./local.py ./code/
RUN pip install --upgrade pip
RUN pip install --no-cache-dir --upgrade -r ./code/requirements.txt
COPY ./src /code/src
CMD ["uvicorn", "src.server:app", "--reload"]
