import inspect
import cloudinary.utils
src = inspect.getsource(cloudinary.utils.cloudinary_url)
print(src[:3000])
