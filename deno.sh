#!/bin/bash

BASE_DIR=$(realpath `dirname "$BASH_SOURCE"`)
export DENO_DIR=$BASE_DIR/.deno
export DENO_PATH=$DENO_DIR/deno
export PATH=$DENO_DIR:$PATH



if ! [ -e $DENO_PATH ];
then
    echo "Downloading deno..."
    wget  https://github.com/denoland/deno/releases/download/v1.30.0/deno-x86_64-unknown-linux-gnu.zip  -O ./deno.zip -nv
    unzip ./deno.zip -d $DENO_DIR  && rm ./deno.zip
fi

DENO_DIR=$DENO_DIR/.deno $DENO_PATH $@