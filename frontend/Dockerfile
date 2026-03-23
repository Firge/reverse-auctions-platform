FROM node:18-alpine

WORKDIR /app

COPY package*.json .

RUN npm ci --verbose

COPY . .

EXPOSE 5173
ENV PATH /app/node_modules/.bin:$PATH

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
