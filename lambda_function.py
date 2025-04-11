from mangum import Mangum 
from src.server import app

lambda_handler = Mangum(app, lifespan="off")