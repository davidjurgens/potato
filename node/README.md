# Potato Node
In order to use better practices within the potato tool, we created a sub directory
to allow for compiled javascript modules to be used within the project. This should
allow us to still support legacy modules while at the same time leveraging the power 
of node and npm.


## Using this sub-project
You should never need to. These modules will be compiled and distributed by jsDelivr
however, I have supplied some quick instructions below should you want to test or roll
out your own versions.


## Quick Intro to node projects
1. Install nodejs (Google it)
2. Run the following in terminal `npm i`
3. Run the following in terminal `npm run dev` 

This will create a development server using vite. Feel free to learn more about the vite
ecosystem and it's features to understand how to deploy and test.

## Running Locally
Sadly with vite not supporting preview builds with the dev server you have to run
 the build and the server seperately.

- In 1st Window: `npm run dev`
- In 2nd Window: `npm run preview`

## Deploying to dist
`npm run build`


## Vite Docs
https://vite.dev/guide/build.html#library-mode