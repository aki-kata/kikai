# -*- coding: utf-8 -*-
# for python3
# 画像検出クラス

import sys
import numpy as np
from skimage import io, feature, color, transform
import pickle
import matplotlib.pyplot as plt

class DetectImg:

    WIDTH, HEIGHT = (64, 64)
    
    def __init__(self, func, filename):
        self.func = func
    
        # 学習結果のパラメータを入力する
        self.cell_size, self.lbp_radius, self.lbp_points, self.params = \
            pickle.load(open(filename, "rb"))
        self.cell_size = int(self.cell_size)
        print("training features spec: cell_size=%d lbp_radius=%d" % \
            (self.cell_size, self.lbp_radius))
    
    def get_params(self):
        return self.params

    # LBPのヒストグラムを計算する
    # 引数: LBP特徴量(numpy), LBP化した画像のサイズ, offset
    # 端からoffset分ずらしてヒストグラムを作成する
    def get_histogram(self, lbp, size_y, size_x, yoffset=0, xoffset=0):
    
        bins = self.lbp_points + 2
        histogram = np.zeros(shape = (int(size_y / self.cell_size), int(size_x / self.cell_size), bins), dtype = np.int)
        
        for y in range(yoffset, size_y - self.cell_size, self.cell_size):
            for x in range(xoffset, size_x - self.cell_size, self.cell_size):
                for dy in range(self.cell_size):
                    for dx in range(self.cell_size):
                        histogram[int(y / self.cell_size), int(x / self.cell_size), int(lbp[y + dy, x + dx])] += 1
        return histogram
    
    
    
    # 画像検出する
    # 引数: 画像, 検出結果の格納場所, 入力画像の縮小率
    def detect_img(self, image, detections, scale):
    
        # LBP特徴量を求める
        lbp = feature.local_binary_pattern(image, self.lbp_points, self.lbp_radius, 'uniform')
    
        # LBP特徴量からヒストグラムを作成し、パーセプトロンなどで計算する
        # cell_sizeが大きいと検出対象がセルをまたいでしまうので、
        # ヒストグラム作成対象をoffset分だけずらす。
        cnt = 0
        for yoffset in range(0, self.cell_size, 2):
            for xoffset in range(0, self.cell_size, 2):
                histogram = self.get_histogram(lbp, image.shape[0], image.shape[1], yoffset, xoffset)
        
                # ヒストグラムの左上から順にセル領域を取り出して、
                # その部分を検出処理する。    
                for y in range(0, histogram.shape[0] - int(self.HEIGHT / self.cell_size)):
                    for x in range(0, histogram.shape[1] - int(self.WIDTH / self.cell_size)):
        
                        # セル領域を一次元にreshapeする
                        # SVMの場合は、reshape(1, -1)しないと大量の警告が出る。むー
                        #features = histogram[y:y + int(self.HEIGHT / self.cell_size),
                        #              x:x + int(self.WIDTH / self.cell_size)].reshape(1, -1)
                        features = histogram[y:y + int(self.HEIGHT / self.cell_size),
                                      x:x + int(self.WIDTH / self.cell_size)].reshape(-1)
            
                        # パーセプトロンなどで計算する
                        score = self.func(features)
            
                        # 検出結果を保存する
                        if score[0] > 0:
                            detections.append({
                                'x': x * self.cell_size / scale,
                                'y': y * self.cell_size / scale,
                                'width': self.WIDTH / scale,
                                'height': self.HEIGHT / scale,
                                'score': score[0]})
                            cnt += 1
        return cnt
            
    # 検出結果の重なりを判定する
    # AND領域とOR領域の面積を計算し、AND/ORの値を返す
    # (重なりがないと0、完全に重なると1)
    def overlap_score(self, a,b):
        left = max(a['x'], b['x'])
        right = min(a['x'] + a['width'], b['x'] + b['width'])
        if left >= right: return 0

        top = max(a['y'], b['y'])
        bottom = min(a['y'] + a['height'], b['y'] + b['height'])
        if top >= bottom: return 0

        # ふたつの領域のAND部分
        intersect = (right - left) * (bottom - top)
        # OR部分
        union = a['width'] * a['height'] + b['width'] * b['height'] - intersect
        
        # (AND領域 / OR領域)の値を返す
        if abs(union) < 0.001:
            return 0    # 0での除算を回避
        else:
            return intersect / union
    
    # 検出結果の重なりを処理する
    # 重なり具合の多い検出結果に対して、スコアの大きい方を残して他を削除する
    # results : 検出結果(リスト型)
    def del_near_results(self, results):
    
        # 重なりを排除する基準(1に近いほど排除しなくなる)
        del_score = 0.3
    
        # 'score'で降順に並び替える
        results = sorted(results, key = lambda d: d['score'], reverse = True)
        
        # 検出結果の重なりを処理する
        # バブルソートの要領でスコアの低い検出結果(の番号)をno_needsに追加する
        no_needs = set()
        for i in range(len(results)):
            if i in no_needs: continue
            for j in range(i +1, len(results)):
                if self.overlap_score(results[i], results[j]) > del_score:
                    no_needs.add(j)
    
        # no_needsに入れた検出結果(の番号)を除いたリストを作る
        results =  [d for i, d in enumerate(results) if not i in no_needs]
        return results

    def detect(self, img_file, title='', answer=None):
        # 画像をグレーに変換する
        target = color.rgb2gray(io.imread(img_file))    
        target_scaled = target + 0
    
        detections = []
        scale_factor = 2.0 ** (-1.0 / 8.0)
    
        # 画像検出する
        # 入力画像を徐々に縮小することで、相対的に検出枠を大きくする
        # つまり検出対象の大きさを変えるということ
        for s in range(32):
            scale = (scale_factor ** s)
            print("Loop %d scale=%.3f detect-size=%d" % (s, scale, int(self.WIDTH/scale)))
    
            # 検出する
            n = self.detect_img(target_scaled, detections, scale)
            if n > 0: print("  %d detected" % n)
    
            # 入力画像を縮小する    
            target_scaled = transform.rescale(target_scaled, scale_factor)
        
        print("-- results -- ")
    
        # 検出結果の出力処理
        # まず入力画像を描画する
        plt.title(title + ' detect result')
        image = io.imread(img_file)
        print("imae size(y,x):", image.shape[0], image.shape[1])
        plt.axis([0, image.shape[1], image.shape[0], 0])
        #io.imshow(image)
        #io.show()
        plt.imshow(image)
    
        # 検出結果の重なりを整理する
        # 戻りはスコア順にソートされている
        detections = self.del_near_results(detections)

        if answer != None:
            d_x1 = answer['x']
            d_y1 = answer['y']
            d_x2 = d_x1 + answer['width']
            d_y2 = d_y1 + answer['height']
            plt.plot( [d_x1, d_x1], [d_y1, d_y2], 'b', lw=1 )
            plt.plot( [d_x1, d_x2], [d_y2, d_y2], 'b', lw=1 )
            plt.plot( [d_x2, d_x2], [d_y2, d_y1], 'b', lw=1 )
            plt.plot( [d_x2, d_x1], [d_y1, d_y1], 'b', lw=1 )
    
        # 検出枠を描画する
        # 上位5件だけとする
        print("detect    score   x   y   w   h")
        ar_detect = np.array(detections)
        for idx in range(ar_detect.shape[0]):
            #print idx, ar_detect[idx]
            d_x1 = ar_detect[idx]['x']
            d_y1 = ar_detect[idx]['y']
            d_x2 = d_x1 + ar_detect[idx]['width']
            d_y2 = d_y1 + ar_detect[idx]['height']
            print("detect %8.1f %3.0f %3.0f %3.0f %3.0f" % ( ar_detect[idx]['score'], ar_detect[idx]['x'], ar_detect[idx]['y'], ar_detect[idx]['width'], ar_detect[idx]['height']))
            # 長方形の書き方がわからない(;_;
            if idx == 0:
                plt.plot( [d_x1, d_x1], [d_y1, d_y2], 'r', lw=3 )
                plt.plot( [d_x1, d_x2], [d_y2, d_y2], 'r', lw=3 )
                plt.plot( [d_x2, d_x2], [d_y2, d_y1], 'r', lw=3 )
                plt.plot( [d_x2, d_x1], [d_y1, d_y1], 'r', lw=3 )
            else:
                plt.plot( [d_x1, d_x1], [d_y1, d_y2], 'g', lw=1 )
                plt.plot( [d_x1, d_x2], [d_y2, d_y2], 'g', lw=1 )
                plt.plot( [d_x2, d_x2], [d_y2, d_y1], 'g', lw=1 )
                plt.plot( [d_x2, d_x1], [d_y1, d_y1], 'g', lw=1 )
            if idx == 4: break
    
        # 描画したものを表示する
        plt.show()


    # 学習結果の検証用に顔検出する
    # バッチ用なので、画像の出力はしない。
    # param_file : パラメータファイル
    # order : 検出結果の何位までを検出したとみなすか
    # overlap_ratio : 正解の位置との重なり具合(0.0 - 1.0)
    # 戻り値 : -1:エラー、 0:検出できず、 1以上 : 検出した順位
    def detect_noplot(self, img_file, answer, order, overlap_ratio):

        # 画像をグレーに変換する
        target = color.rgb2gray(io.imread(img_file))    
        target_scaled = target + 0
    
        detections = []
        scale_factor = 2.0 ** (-1.0 / 8.0)
    
        # 画像検出する
        # 入力画像を徐々に縮小することで、相対的に検出枠を大きくする
        # つまり検出対象の大きさを変えるということ
        for s in range(32):
            scale = (scale_factor ** s)
    
            # 検出する
            self.detect_img(target_scaled, detections, scale)
    
            # 入力画像を縮小する    
            target_scaled = transform.rescale(target_scaled, scale_factor)

        # 検出結果の重なりを整理する
        # 戻りはスコア順にソートされている
        detections = self.del_near_results(detections)
    
        print("answer %3.0f %3.0f %3.0f %3.0f" % ( answer['x'], answer['y'], answer['width'], answer['height']))

        res = 0
        ar_detect = np.array(detections)
        for idx in range(ar_detect.shape[0]):

            s = self.overlap_score(answer, detections[idx])
            print("idx=%d  s=%f" % (idx+1, s))
            if s > overlap_ratio:
                print("OK idx=%d score=%f" % (idx+1, s))
                res = idx +1
                break

            if idx == order-1: break
    
        return res


# Main
if __name__ == '__main__':
    import percep_cls
    c = percep_cls.Perceptron()
    detect = DetectImg(c.predict, sys.argv[1])

    params = detect.get_params()
    c.set_params(params)

    detect.detect(sys.argv[2])

