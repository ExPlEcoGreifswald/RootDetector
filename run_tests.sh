#!/bin/bash



if [[ $@ = '--build-docker' ]]; then
    echo "Building docker";
    base/run_tests.sh --build-docker
    sudo docker build --rm -f tests/docker/Dockerfile -t roots_test_docker  ./
    sudo docker image prune -f

else
    DOCKER_IMAGE=roots_test_docker $(dirname ${BASH_SOURCE:-$0})/base/run_tests.sh $@
fi
