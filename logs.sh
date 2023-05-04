# get id of container with name to_chat and save to variable
CONTAINER_ID=$(docker ps -aqf "name=to_chat")
docker logs -f $CONTAINER_ID
