import cv2
import numpy as np
import onnxruntime as ort
from typing import List, Tuple
from PIL import Image, ImageEnhance
import requests
from io import BytesIO
import itertools
import traceback

class WordMatcher:
    def __init__(self, yolo_model_path: str, resnet_model_path: str,
                 static_base_url: str = "https://static.botion.com/",
                 referer: str = "https://bcaptcha.botion.com/"):
        """
        初始化文字点选匹配器 (支持3或4个图标) - 国际版(botion)定制

        static_base_url: 图标/背景图的静态资源域名 (国际版为 static.botion.com)
        referer: 下载图片时使用的 Referer
        """
        self.YOLO_MODEL_PATH = yolo_model_path
        self.RESNET_MODEL_PATH = resnet_model_path
        self.static_base_url = static_base_url.rstrip('/') + '/'

        # 坐标转换参数
        self.COORD_SCALE_X = 300.0
        self.COORD_SCALE_Y = 200.0
        self.COORD_MULTIPLIER = 10000

        # YOLO 配置 (国际版 botion 字体较细, 阈值下调至 0.4 检测更稳定)
        self.YOLO_INPUT_SIZE = 320
        self.CONF_THRESHOLD = 0.4
        self.NMS_THRESHOLD = 0.45

        # Siamese 模型配置
        self.RESNET_INPUT_SIZE = 128
        self.DISTANCE_THRESHOLD = 0.5

        # 请求头
        self.headers = {
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        }

        # 模型输入名
        self.resnet_input_name_1 = None
        self.resnet_input_name_2 = None

        # 初始化模型
        self._init_models()

        # Siamese 标准预处理参数，等价替代 torchvision.transforms
        self.mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape((3, 1, 1))
        self.std = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape((3, 1, 1))

    def _init_models(self):
        """初始化YOLO和Siamese模型"""
        try:
            self.yolo_session = ort.InferenceSession(self.YOLO_MODEL_PATH, providers=['CPUExecutionProvider'])
            self.yolo_input_name = self.yolo_session.get_inputs()[0].name

            self.resnet_session = ort.InferenceSession(self.RESNET_MODEL_PATH, providers=['CPUExecutionProvider'])
            inputs = self.resnet_session.get_inputs()
            if len(inputs) < 2:
                raise ValueError("Siamese ONNX模型输入数量不足2个")
            self.resnet_input_name_1 = inputs[0].name
            self.resnet_input_name_2 = inputs[1].name
        except Exception as e:
            raise Exception(f"模型初始化失败: {e}")

    def _download_image(self, url: str) -> bytes:
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            return response.content
        except Exception as e:
            raise Exception(f"图片下载失败: {e}")

    def _bytes_to_cv2(self, image_bytes: bytes) -> np.ndarray:
        try:
            image_array = np.frombuffer(image_bytes, np.uint8)
            image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("无法解码图片")
            return image
        except Exception as e:
            raise Exception(f"图片转换失败: {e}")

    def _letterbox(self, img: np.ndarray, new_shape: Tuple[int, int]) -> Tuple[np.ndarray, float, Tuple[float, float]]:
        shape = img.shape[:2]
        new_w, new_h = new_shape
        r = min(new_w / shape[1], new_h / shape[0])
        new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
        dw, dh = new_w - new_unpad[0], new_h - new_unpad[1]
        dw /= 2
        dh /= 2
        if shape[::-1] != new_unpad:
            img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114,114,114))
        return img, r, (dw, dh)

    def _transparent_to_white(self, image: Image.Image) -> Image.Image:
        if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
            background = Image.new('RGB', image.size, (255, 255, 255))
            rgba_image = image.convert('RGBA')
            background.paste(rgba_image, (0, 0), rgba_image.split()[3])
            return background
        else:
            return image.convert('RGB')

    def _preprocess_siamese_image(self, image: Image.Image, enhance_contrast: bool) -> np.ndarray:
        if enhance_contrast:
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.5)
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(1.5)
        image = image.resize((self.RESNET_INPUT_SIZE, self.RESNET_INPUT_SIZE), Image.BILINEAR)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        img_np = np.array(image, dtype=np.float32) / 255.0
        tensor = img_np.transpose((2, 0, 1))
        tensor = (tensor - self.mean) / self.std
        return tensor.astype(np.float32)

    def _preprocess_icon(self, icon_bytes: bytes, enhance_contrast: bool = True) -> np.ndarray:
        icon = Image.open(BytesIO(icon_bytes))
        icon = self._transparent_to_white(icon)
        return self._preprocess_siamese_image(icon, enhance_contrast)

    def _preprocess_crop(self, image: np.ndarray, enhance_contrast: bool = True) -> np.ndarray:
        if len(image.shape) == 3 and image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(image)
        if enhance_contrast:
            enhancer = ImageEnhance.Contrast(pil_image)
            pil_image = enhancer.enhance(1.2)
            enhancer = ImageEnhance.Sharpness(pil_image)
            pil_image = enhancer.enhance(1.1)
        return self._preprocess_siamese_image(pil_image, enhance_contrast=False)

    def _euclidean_distance(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        return np.linalg.norm(vec1 - vec2)

    def _process_coordinates(self, x: int, y: int) -> Tuple[int, int]:
        processed_x = int((x / self.COORD_SCALE_X) * self.COORD_MULTIPLIER)
        processed_y = int((y / self.COORD_SCALE_Y) * self.COORD_MULTIPLIER)
        return processed_x, processed_y

    def _yolo_detect_and_crop(self, bg_image_bytes: bytes) -> Tuple[List[np.ndarray], List[Tuple[int, int]]]:
        src_img = self._bytes_to_cv2(bg_image_bytes)
        h_orig, w_orig = src_img.shape[:2]
        img_resized, scale, (pad_w, pad_h) = self._letterbox(src_img, (self.YOLO_INPUT_SIZE, self.YOLO_INPUT_SIZE))
        img_input = img_resized.transpose((2, 0, 1))
        img_input = np.ascontiguousarray(img_input).astype(np.float32) / 255.0
        img_input = np.expand_dims(img_input, 0)
        outputs = self.yolo_session.run(None, {self.yolo_input_name: img_input})[0]

        boxes, confidences = [], []
        for row in outputs[0]:
            objectness_score = row[4]
            if objectness_score >= self.CONF_THRESHOLD:
                class_scores = row[5:]
                max_class_score = np.max(class_scores)
                final_confidence = objectness_score * max_class_score
                if final_confidence >= self.CONF_THRESHOLD:
                    xc, yc, w, h = row[0:4]
                    left = int(xc - w / 2)
                    top = int(yc - h / 2)
                    boxes.append([left, top, int(w), int(h)])
                    confidences.append(float(final_confidence))
        indices_np = cv2.dnn.NMSBoxes(boxes, confidences, self.CONF_THRESHOLD, self.NMS_THRESHOLD)
        if isinstance(indices_np, np.ndarray) and indices_np.size > 0:
            indices = indices_np.flatten().tolist()
        else:
            indices = []
        if indices:
            indices_with_conf = [(idx, confidences[idx]) for idx in indices]
            indices_with_conf.sort(key=lambda x: x[1], reverse=True)
            indices = [idx for idx, conf in indices_with_conf]

        cropped_images, center_coordinates = [], []
        for idx in indices:
            box = boxes[idx]
            left_padded, top_padded, w_padded, h_padded = box
            left_unpad = left_padded - pad_w
            top_unpad = top_padded - pad_h
            x = int(round(left_unpad / scale))
            y = int(round(top_unpad / scale))
            w = int(round(w_padded / scale))
            h = int(round(h_padded / scale))
            x = max(0, min(x, w_orig - 1))
            y = max(0, min(y, h_orig - 1))
            w = max(1, min(w, w_orig - x))
            h = max(1, min(h, h_orig - y))
            cropped_img = src_img[y:y + h, x:x + w]
            cropped_images.append(cropped_img)
            x_center = x + w // 2
            y_center = y + h // 2
            center_coordinates.append((x_center, y_center))

        return cropped_images, center_coordinates

    def _get_siamese_features(self, image_batch: np.ndarray, is_icon: bool) -> np.ndarray:
        placeholder = np.zeros_like(image_batch, dtype=np.float32)
        if is_icon:
            input_feed = {
                self.resnet_input_name_1: image_batch,
                self.resnet_input_name_2: placeholder
            }
            ort_outs = self.resnet_session.run(None, input_feed)
            return ort_outs[0]
        else:
            input_feed = {
                self.resnet_input_name_1: placeholder,
                self.resnet_input_name_2: image_batch
            }
            ort_outs = self.resnet_session.run(None, input_feed)
            return ort_outs[1]

    def _match_icons_with_crops(self, icon_bytes_list: List[bytes], cropped_images: List[np.ndarray]) -> List[int]:
        N_icons = len(icon_bytes_list)
        N_crops = len(cropped_images)
        if N_crops < N_icons:
            while len(cropped_images) < N_icons:
                cropped_images.append(cropped_images[0])

        icon_batch = np.array([self._preprocess_icon(b) for b in icon_bytes_list], dtype=np.float32)
        crop_batch = np.array([self._preprocess_crop(c) for c in cropped_images], dtype=np.float32)

        icon_features = self._get_siamese_features(icon_batch, is_icon=True)
        crop_features = self._get_siamese_features(crop_batch, is_icon=False)

        distance_matrix = np.zeros((N_icons, N_crops))
        for i in range(N_icons):
            for j in range(N_crops):
                distance_matrix[i, j] = self._euclidean_distance(icon_features[i], crop_features[j])

        best_sum_distance = float('inf')
        best_matches = []
        for perm in itertools.permutations(range(N_crops), N_icons):
            total_dist = sum(distance_matrix[i, perm[i]] for i in range(N_icons))
            if total_dist < best_sum_distance:
                best_sum_distance = total_dist
                best_matches = list(perm)
        return best_matches

    def match_words(self, bg_url: str, ques_list: List[str]) -> List[List[int]]:
        """
        支持传入完整ques数组，如：
        match_words("https://static.geetest.com/bg.jpg", ["/x1.png", "/x2.png", "/x3.png", "/x4.png"])
        """
        try:
            base_url = self.static_base_url
            bg_bytes = self._download_image(bg_url)
            icon_bytes_list = [self._download_image(base_url + q) for q in ques_list]

            cropped_images, center_coordinates = self._yolo_detect_and_crop(bg_bytes)
            if len(cropped_images) == 0:
                return []

            matched_indices = self._match_icons_with_crops(icon_bytes_list, cropped_images)

            final_coordinates = []
            for i, match_idx in enumerate(matched_indices):
                original_x, original_y = center_coordinates[match_idx]
                processed_x, processed_y = self._process_coordinates(original_x, original_y)
                final_coordinates.append([processed_x, processed_y])
            return final_coordinates
        except Exception:
            traceback.print_exc()
            return []
